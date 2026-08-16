"""
Message Queue

Redis-based asynchronous message queue for processing messages.
"""

import logging
import json
import os
from typing import Optional, Dict, Any, List
import asyncio

logger = logging.getLogger(__name__)


class MessageQueue:
    """Redis-based message queue for async processing

    Provides prioritized message queueing, retry queue,
    and dead letter queue for failed messages.
    """

    def __init__(self, redis_url: Optional[str] = None):
        """Initialize message queue

        Args:
            redis_url: Redis connection URL
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis = None


        self.pending_queue = "messages:pending"
        self.retry_queue = "messages:retry"
        self.dead_letter_queue = "messages:dead"


        self._last_redis_failure_time = None
        self._redis_failure_cooldown = 3600

    def _get_redis(self):
        """Get Redis client"""
        if self._redis is None:
            try:
                import redis
                from datetime import datetime
                self._redis = redis.from_url(self.redis_url, decode_responses=True)
                logger.info("Connected to Redis for message queue")
            except Exception as e:

                from datetime import datetime
                now = datetime.now()
                if self._last_redis_failure_time:
                    time_since_last = (now - self._last_redis_failure_time).total_seconds()
                    if time_since_last < self._redis_failure_cooldown:
                        return None
                self._last_redis_failure_time = now
                logger.warning(f"Failed to connect to Redis: {e}")
                logger.warning("Message queue will not be available")
                self._redis = None
                return None
        return self._redis

    async def enqueue(self, message_data: Dict[str, Any], priority: int = 0) -> bool:
        """Enqueue a message for sending

        Args:
            message_data: Message data dictionary
            priority: Priority score (higher = more important)

        Returns:
            True if successful
        """
        redis = self._get_redis()
        if redis is None:
            logger.warning("Message queue not available (Redis not connected)")
            return False

        try:


            result = await redis.zadd(
                self.pending_queue,
                {json.dumps(message_data): priority}
            )

            logger.debug(f"Enqueued message {message_data.get('id')} with priority {priority}")
            return result > 0

        except Exception as e:
            logger.error(f"Error enqueuing message: {e}")
            return False

    async def dequeue(self) -> Optional[Dict[str, Any]]:
        """Dequeue next message (highest priority first)

        Returns:
            Message data dictionary or None
        """
        redis = self._get_redis()
        if redis is None:
            logger.warning("Message queue not available (Redis not connected)")
            return None

        try:

            result = await redis.zpopmax(self.pending_queue)

            if result:
                data, _ = result[0]
                message_data = json.loads(data)
                logger.debug(f"Dequeued message {message_data.get('id')}")
                return message_data

            return None

        except Exception as e:
            logger.error(f"Error dequeuing message: {e}")
            return None

    async def peek(self) -> Optional[Dict[str, Any]]:
        """Peek at next message without removing it

        Returns:
            Message data dictionary or None
        """
        redis = self._get_redis()
        if redis is None:
            logger.warning("Message queue not available (Redis not connected)")
            return None

        try:

            result = await redis.zrange(self.pending_queue, -1, -1, withscores=True)

            if result:
                data, _ = result[0]
                message_data = json.loads(data)
                return message_data

            return None

        except Exception as e:
            logger.error(f"Error peeking at queue: {e}")
            return None

    async def enqueue_retry(self, message_data: Dict[str, Any]) -> bool:
        """Enqueue a message for retry

        Args:
            message_data: Message data dictionary

        Returns:
            True if successful
        """
        redis = self._get_redis()

        try:

            result = await redis.rpush(
                self.retry_queue,
                json.dumps(message_data)
            )

            logger.debug(f"Enqueued retry for message {message_data.get('id')}")
            return result > 0

        except Exception as e:
            logger.error(f"Error enqueuing retry: {e}")
            return False

    async def dequeue_retry(self) -> Optional[Dict[str, Any]]:
        """Dequeue next retry message (FIFO)

        Returns:
            Message data dictionary or None
        """
        redis = self._get_redis()

        try:
            data = await redis.lpop(self.retry_queue)

            if data:
                message_data = json.loads(data)
                logger.debug(f"Dequeued retry for message {message_data.get('id')}")
                return message_data

            return None

        except Exception as e:
            logger.error(f"Error dequeuing retry: {e}")
            return None

    async def move_to_dead_letter_queue(self, message_data: Dict[str, Any],
                                        reason: str = "Max retries exceeded") -> bool:
        """Move message to dead letter queue

        Args:
            message_data: Message data dictionary
            reason: Reason for moving to DLQ

        Returns:
            True if successful
        """
        redis = self._get_redis()

        try:

            dlq_entry = {
                **message_data,
                "reason": reason,
                "moved_at": asyncio.get_event_loop().time()
            }

            result = await redis.rpush(
                self.dead_letter_queue,
                json.dumps(dlq_entry)
            )

            logger.warning(f"Moved message {message_data.get('id')} to dead letter queue: {reason}")
            return result > 0

        except Exception as e:
            logger.error(f"Error moving to dead letter queue: {e}")
            return False

    async def get_queue_size(self) -> Dict[str, int]:
        """Get sizes of all queues

        Returns:
            Dictionary with queue sizes
        """
        redis = self._get_redis()
        if redis is None:
            logger.warning("Message queue not available (Redis not connected)")
            return {
                "pending": 0,
                "retry": 0,
                "dead_letter": 0
            }

        try:
            return {
                "pending": await redis.zcard(self.pending_queue),
                "retry": await redis.llen(self.retry_queue),
                "dead_letter": await redis.llen(self.dead_letter_queue)
            }

        except Exception as e:
            logger.error(f"Error getting queue sizes: {e}")
            return {
                "pending": 0,
                "retry": 0,
                "dead_letter": 0
            }

    async def clear_queue(self, queue_name: str = "pending") -> int:
        """Clear a specific queue

        Args:
            queue_name: Queue name (pending, retry, dead_letter)

        Returns:
            Number of messages cleared
        """
        redis = self._get_redis()

        queue_map = {
            "pending": self.pending_queue,
            "retry": self.retry_queue,
            "dead_letter": self.dead_letter_queue
        }

        queue = queue_map.get(queue_name)
        if not queue:
            logger.error(f"Unknown queue: {queue_name}")
            return 0

        try:
            if queue_name == "pending":
                count = await redis.zcard(queue)
                await redis.delete(queue)
            else:
                count = await redis.llen(queue)
                await redis.delete(queue)

            logger.info(f"Cleared {count} messages from {queue_name} queue")
            return count

        except Exception as e:
            logger.error(f"Error clearing queue: {e}")
            return 0

    async def get_dead_letter_queue(self) -> List[Dict[str, Any]]:
        """Get all messages from dead letter queue

        Returns:
            List of dead letter messages
        """
        redis = self._get_redis()

        try:
            data_list = await redis.lrange(self.dead_letter_queue, 0, -1)

            return [
                json.loads(data)
                for data in data_list
            ]

        except Exception as e:
            logger.error(f"Error getting dead letter queue: {e}")
            return []

    async def retry_dead_letter_message(self, index: int = 0) -> bool:
        """Retry a message from dead letter queue

        Args:
            index: Index of message to retry

        Returns:
            True if successful
        """
        redis = self._get_redis()

        try:

            data = await redis.lindex(self.dead_letter_queue, index)

            if data:
                message_data = json.loads(data)


                await redis.lrem(self.dead_letter_queue, 1, data)


                return await self.enqueue(message_data)

            return False

        except Exception as e:
            logger.error(f"Error retrying dead letter message: {e}")
            return False
