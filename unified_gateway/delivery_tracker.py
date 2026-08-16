"""
Delivery Tracker

Tracks message delivery status across all platforms with retry logic.
"""

import logging
import json
import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
import uuid

from .models import DeliveryInfo, DeliveryStatus, Platform, UnifiedMessage

logger = logging.getLogger(__name__)


class DeliveryTracker:
    """Track message delivery status across platforms

    Provides delivery tracking, retry logic, and dead letter queue
    for failed messages.
    """

    def __init__(self, storage_backend: str = "json", storage_path: Optional[str] = None,
                 retry_config: Optional[Dict[str, Any]] = None):
        """Initialize delivery tracker

        Args:
            storage_backend: Storage backend ('json' or 'redis')
            storage_path: Path to storage file or Redis URL
            retry_config: Retry configuration (max_attempts, base_delay, max_delay)
        """
        self.storage_backend = storage_backend

        if storage_backend == "json":
            default_path = "data/deliveries.json"
            raw_path = storage_path or default_path
            if not os.path.isabs(raw_path):

                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                self.storage_path = os.path.join(project_root, raw_path)
            else:
                self.storage_path = raw_path
            self._ensure_storage_dir()
        elif storage_backend == "redis":
            self.redis_url = storage_path or os.getenv("REDIS_URL", "redis://localhost:6379/0")
            self._redis = None


        self.retry_config = retry_config or {
            "max_attempts": 3,
            "base_delay": 2.0,
            "max_delay": 60.0
        }


        self._last_redis_failure_time = None
        self._redis_failure_cooldown = 3600

    def _ensure_storage_dir(self):
        """Ensure storage directory exists"""
        if self.storage_path:
            dir_path = os.path.dirname(self.storage_path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)

    def _load_deliveries(self) -> Dict:
        """Load delivery information from storage

        Returns:
            Dictionary of delivery_id -> DeliveryInfo
        """
        if self.storage_backend == "json":
            if os.path.exists(self.storage_path):
                try:
                    with open(self.storage_path, 'r') as f:
                        data = json.load(f)
                        return data
                except Exception as e:
                    logger.error(f"Error loading deliveries: {e}")
                    return {}
            return {}

        elif self.storage_backend == "redis":
            if self._redis is None:
                try:
                    import redis
                    self._redis = redis.from_url(self.redis_url, decode_responses=True)
                    logger.info("Connected to Redis for delivery tracker")
                except Exception as e:
                    logger.warning(f"Failed to connect to Redis: {e}")
                    logger.warning("Falling back to in-memory storage for deliveries")
                    asyncio.create_task(self._send_redis_failure_notification("_load_deliveries", "in-memory"))
                    self.storage_backend = "memory"
                    return {}

            try:
                data = self._redis.get("deliveries")
                if data:
                    return json.loads(data)
                return {}
            except Exception as e:
                logger.warning("Redis unavailable for delivery loading: %s", e)
                logger.debug("Falling back to empty deliveries")
                return {}

        return {}

    def _save_deliveries(self, deliveries: Dict):
        """Save delivery information to storage

        Args:
            deliveries: Dictionary of delivery_id -> DeliveryInfo
        """
        if self.storage_backend == "json":
            try:
                with open(self.storage_path, 'w') as f:
                    json.dump(deliveries, f, indent=2)
            except Exception as e:
                logger.error(f"Error saving deliveries: {e}")

        elif self.storage_backend == "redis":
            if self._redis is None:
                try:
                    import redis
                    self._redis = redis.from_url(self.redis_url, decode_responses=True)
                    logger.debug("Connected to Redis for delivery tracker")
                except Exception as e:
                    logger.warning("Redis unavailable for delivery tracker: %s", e)
                    self.storage_backend = "memory"
                    return

            try:
                self._redis.set("deliveries", json.dumps(deliveries))
            except Exception as e:
                logger.warning("Redis unavailable for delivery save: %s", e)
                self.storage_backend = "memory"
                return

        elif self.storage_backend == "memory":
            return

    async def track_message(self, message: UnifiedMessage) -> str:
        """Start tracking a message

        Args:
            message: UnifiedMessage to track

        Returns:
            Delivery ID
        """
        delivery_id = str(uuid.uuid4())

        delivery_info = DeliveryInfo(
            id=delivery_id,
            message_id=message.id,
            platform=message.platform,
            user_id=message.user_id,
            status=DeliveryStatus.QUEUED,
            attempts=0,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )


        deliveries = self._load_deliveries()
        deliveries[delivery_id] = delivery_info.to_dict()
        self._save_deliveries(deliveries)

        logger.debug(f"Started tracking delivery {delivery_id} for message {message.id}")
        return delivery_id

    async def update_status(self, delivery_id: str, status: DeliveryStatus,
                           error: Optional[str] = None):
        """Update delivery status

        Args:
            delivery_id: Delivery ID
            status: New status
            error: Error message (if failed)
        """
        deliveries = self._load_deliveries()

        if delivery_id not in deliveries:
            logger.warning(f"Delivery {delivery_id} not found")
            return

        delivery_data = deliveries[delivery_id]
        delivery_data["status"] = status.value
        delivery_data["updated_at"] = datetime.now().isoformat()


        if status == DeliveryStatus.SENT and not delivery_data.get("sent_at"):
            delivery_data["sent_at"] = datetime.now().isoformat()
        elif status == DeliveryStatus.DELIVERED and not delivery_data.get("delivered_at"):
            delivery_data["delivered_at"] = datetime.now().isoformat()

        if error:
            delivery_data["last_error"] = error
            delivery_data["attempts"] += 1


        if status == DeliveryStatus.FAILED:
            if delivery_data["attempts"] < self.retry_config["max_attempts"]:

                delivery_data["status"] = DeliveryStatus.RETRYING.value
                logger.info(f"Delivery {delivery_id} failed, scheduling retry (attempt {delivery_data['attempts']})")


                asyncio.create_task(self._schedule_retry(delivery_data))
            else:

                await self._move_to_dead_letter_queue(delivery_data)
                logger.error(f"Delivery {delivery_id} failed after max attempts, moved to dead letter queue")


                await self._send_delivery_failure_notification(
                    delivery_data.get("platform", "unknown"),
                    delivery_data.get("user_id", "unknown"),
                    delivery_data.get("last_error", "Unknown error"),
                    delivery_data.get("attempts", 0)
                )

        self._save_deliveries(deliveries)

    async def _schedule_retry(self, delivery_data: Dict):
        """Schedule message retry with exponential backoff

        Args:
            delivery_data: Delivery information dictionary
        """
        attempt = delivery_data.get("attempts", 1)


        delay = min(
            self.retry_config["base_delay"] * (2 ** (attempt - 1)),
            self.retry_config["max_delay"]
        )

        logger.info(f"Scheduling retry for delivery {delivery_data['id']} in {delay}s")


        await asyncio.sleep(delay)


        await self.update_status(delivery_data["id"], DeliveryStatus.QUEUED)

    async def _move_to_dead_letter_queue(self, delivery_data: Dict):
        """Move failed delivery to dead letter queue

        Args:
            delivery_data: Delivery information dictionary
        """
        dlq_path = "data/dead_letter_queue.json"


        if os.path.exists(dlq_path):
            try:
                with open(dlq_path, 'r') as f:
                    dlq = json.load(f)
            except:
                dlq = []
        else:
            dlq = []


        dlq.append({
            "delivery_id": delivery_data["id"],
            "message_id": delivery_data["message_id"],
            "platform": delivery_data["platform"],
            "user_id": delivery_data["user_id"],
            "status": DeliveryStatus.FAILED.value,
            "attempts": delivery_data["attempts"],
            "last_error": delivery_data.get("last_error"),
            "created_at": delivery_data["created_at"],
            "moved_to_dlq": datetime.now().isoformat()
        })


        try:
            with open(dlq_path, 'w') as f:
                json.dump(dlq, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving to dead letter queue: {e}")

    def get_delivery(self, delivery_id: str) -> Optional[DeliveryInfo]:
        """Get delivery information

        Args:
            delivery_id: Delivery ID

        Returns:
            DeliveryInfo or None
        """
        deliveries = self._load_deliveries()

        if delivery_id in deliveries:
            return DeliveryInfo.from_dict(deliveries[delivery_id])

        return None

    def get_deliveries_for_message(self, message_id: str) -> list:
        """Get all delivery attempts for a message

        Args:
            message_id: Message ID

        Returns:
            List of DeliveryInfo
        """
        deliveries = self._load_deliveries()

        return [
            DeliveryInfo.from_dict(d)
            for d in deliveries.values()
            if d.get("message_id") == message_id
        ]

    def get_deliveries_for_user(self, user_id: str, platform: Optional[str] = None) -> list:
        """Get all deliveries for a user

        Args:
            user_id: User ID
            platform: Optional platform filter

        Returns:
            List of DeliveryInfo
        """
        deliveries = self._load_deliveries()

        result = []
        for delivery_data in deliveries.values():
            if delivery_data.get("user_id") == user_id:
                if platform is None or delivery_data.get("platform") == platform:
                    result.append(DeliveryInfo.from_dict(delivery_data))

        return result

    def cleanup_old_deliveries(self, days: int = 30):
        """Clean up old delivery records

        Args:
            days: Age threshold in days
        """
        deliveries = self._load_deliveries()
        cutoff = datetime.now() - timedelta(days=days)

        to_delete = []
        for delivery_id, delivery_data in deliveries.items():
            created_at = datetime.fromisoformat(delivery_data.get("created_at", ""))
            if created_at < cutoff:
                to_delete.append(delivery_id)

        for delivery_id in to_delete:
            del deliveries[delivery_id]

        self._save_deliveries(deliveries)

        logger.info(f"Cleaned up {len(to_delete)} old delivery records")

    async def _send_redis_failure_notification(self, operation: str, fallback_used: str):
        """Send Redis failure notification with deduplication"""

        from datetime import datetime, timedelta
        now = datetime.now()

        if self._last_redis_failure_time:
            time_since_last = (now - self._last_redis_failure_time).total_seconds()
            if time_since_last < self._redis_failure_cooldown:
                logger.debug(f"Redis failure notification suppressed (cooldown: {self._redis_failure_cooldown - time_since_last:.0f}s remaining)")
                return

        self._last_redis_failure_time = now

        try:
            from notification_system.service import get_notification_service
            service = get_notification_service()
            await service.send_redis_failure(operation, fallback_used)
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Failed to send Redis failure notification: {e}")

    async def _send_delivery_failure_notification(self, platform: str, recipient: str, reason: str, retry_count: int):
        """Send delivery failure notification"""
        try:
            from notification_system.service import get_notification_service
            service = get_notification_service()
            await service.send_delivery_failure(platform, recipient, reason, retry_count)
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Failed to send delivery failure notification: {e}")
