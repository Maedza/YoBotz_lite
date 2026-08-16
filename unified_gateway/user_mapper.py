"""
User Mapper

Maps platform-specific user IDs to unified user IDs for cross-platform support.
"""

import logging
import json
import os
from typing import Dict, Optional
import uuid

logger = logging.getLogger(__name__)


class UserMapper:
    """Maps platform-specific user IDs to unified user IDs

    Enables cross-platform user identity management, allowing users
    to have a unified identity across Telegram.
    """

    def __init__(self, storage_backend: str = "json", storage_path: Optional[str] = None):
        """Initialize user mapper

        Args:
            storage_backend: Storage backend ('json' or 'redis')
            storage_path: Path to storage file or Redis URL
        """
        self.storage_backend = storage_backend


        self._memory_mappings = {}


        if storage_backend == "json":
            default_path = "data/user_mappings.json"

            raw_path = storage_path or default_path
            if not os.path.isabs(raw_path):

                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                self.storage_path = os.path.join(project_root, raw_path)
            else:
                self.storage_path = raw_path
        elif storage_backend == "redis":

            self.storage_path = storage_path or os.getenv("REDIS_URL", "redis://localhost:6379/0")
            self.redis_url = self.storage_path
            self._redis = None

            fallback_raw = "data/user_mappings_fallback.json"
            if not os.path.isabs(fallback_raw):
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                self.fallback_storage_path = os.path.join(project_root, fallback_raw)
            else:
                self.fallback_storage_path = fallback_raw

            try:
                if os.path.exists(self.fallback_storage_path):
                    with open(self.fallback_storage_path, 'r') as f:
                        self._memory_mappings = json.load(f)
                        logger.info(f"Loaded {len(self._memory_mappings)} mappings from Redis fallback file")
            except Exception as e:
                logger.warning(f"Could not load Redis fallback: {e}")
        else:
            self.storage_path = None


        self._ensure_storage_dir()


        self._last_redis_failure_time = None
        self._redis_failure_cooldown = 3600

    def _ensure_storage_dir(self):
        """Ensure storage directory exists"""

        paths_to_check = []
        if self.storage_path:
            paths_to_check.append(os.path.dirname(self.storage_path))
        if hasattr(self, 'fallback_storage_path') and self.fallback_storage_path:
            paths_to_check.append(os.path.dirname(self.fallback_storage_path))

        for dir_path in paths_to_check:
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)

    def _load_mappings(self) -> Dict:
        """Load user mappings from storage

        Returns:
            Dictionary of user mappings
        """
        if self.storage_backend == "json":

            if os.path.exists(self.storage_path):
                try:
                    with open(self.storage_path, 'r') as f:
                        data = json.load(f)
                        if data:
                            return data
                except Exception as e:
                    logger.error(f"Error loading user mappings: {e}")


            if hasattr(self, 'fallback_storage_path') and os.path.exists(self.fallback_storage_path):
                try:
                    with open(self.fallback_storage_path, 'r') as f:
                        data = json.load(f)
                        if data:
                            logger.info(f"Loaded {len(data)} user mappings from fallback file")
                            return data
                except Exception as e:
                    logger.warning(f"Error loading fallback mappings: {e}")

            return {}

        elif self.storage_backend == "redis":
            if self._redis is None:
                try:
                    import redis
                    self._redis = redis.from_url(self.redis_url, decode_responses=True)
                    logger.debug("Connected to Redis for user mapper")
                except Exception as e:
                    logger.warning("Redis unavailable for user mapper: %s", e)
                    self.storage_backend = "memory"

                    return self._memory_mappings.copy()

            try:
                data = self._redis.get("user_mappings")
                if data:
                    return json.loads(data)

                logger.warning("Redis has no user mappings data, checking fallback file")
                return self._memory_mappings.copy()
            except Exception:
                logger.warning("Redis unavailable for user mapper, switching to in-memory")
                self.storage_backend = "memory"
                return self._memory_mappings.copy()


        elif self.storage_backend == "memory":
            return self._memory_mappings.copy()

        return {}

    def _save_mappings(self, mappings: Dict):
        """Save user mappings to storage

        Args:
            mappings: Dictionary of user mappings
        """
        if self.storage_backend == "json":
            try:

                os.makedirs(os.path.dirname(self.storage_path) or '.', exist_ok=True)
                with open(self.storage_path, 'w') as f:
                    json.dump(mappings, f, indent=2)
                logger.debug(f"Saved {len(mappings)} user mappings to primary file")
            except Exception as e:
                logger.error(f"Error saving user mappings: {e}")


            try:
                if hasattr(self, 'fallback_storage_path'):
                    with open(self.fallback_storage_path, 'w') as f:
                        json.dump(mappings, f, indent=2)
                    logger.debug(f"Saved {len(mappings)} user mappings to fallback file")
            except Exception as e:
                logger.warning(f"Error saving fallback mappings: {e}")

        elif self.storage_backend == "redis":
            if self._redis is None:
                try:
                    import redis
                    self._redis = redis.from_url(self.redis_url, decode_responses=True)
                    logger.debug("Connected to Redis for user mapper")
                except Exception as e:
                    logger.warning("Redis unavailable for user mapper save: %s", e)
                    self._save_to_fallback_file(mappings)
                    self._memory_mappings = mappings.copy()
                    return

            try:
                self._redis.set("user_mappings", json.dumps(mappings))

                self._memory_mappings = mappings.copy()
                self._save_to_fallback_file(mappings)
            except Exception as e:
                logger.error(f"Error saving user mappings to Redis: {e}")
                logger.warning("Saving to JSON fallback file instead")

                self._save_to_fallback_file(mappings)
                self._memory_mappings = mappings.copy()


        elif self.storage_backend == "memory":
            self._memory_mappings = mappings.copy()
            self._save_to_fallback_file(mappings)
            logger.debug(f"Saved {len(mappings)} user mappings to in-memory + fallback file")

    def get_or_create(self, platform: str, platform_user_id: str) -> str:
        """Get or create unified user ID

        Args:
            platform: Platform name (e.g. telegram)
            platform_user_id: Platform-specific user ID

        Returns:
            Unified user ID
        """

        logger.debug(f"get_or_create called: platform={platform}, platform_user_id={platform_user_id}")


        mappings = self._load_mappings()

        logger.debug(f"Loaded {len(mappings)} mappings from storage")


        for unified_id, platform_mappings in mappings.items():
            logger.debug(f"Checking {unified_id}: {platform_mappings}")
            if platform_mappings.get(platform) == platform_user_id:
                logger.debug(f"Found existing mapping: {platform}:{platform_user_id} -> {unified_id}")
                return unified_id


        for unified_id, platform_mappings in mappings.items():
            if isinstance(platform_mappings, dict) and platform_user_id in platform_mappings.values():
                logger.info(f"Found mapping via reverse lookup: {platform}:{platform_user_id} -> {unified_id}")
                return unified_id


        if not mappings or (self.storage_backend == "memory" and not mappings):
            logger.warning(f"Mappings storage failed, creating in-memory mapping")


        unified_id = f"user_{uuid.uuid4().hex[:12]}"


        if unified_id not in mappings:
            mappings[unified_id] = {}
        mappings[unified_id][platform] = platform_user_id

        self._save_mappings(mappings)

        logger.info(f"Created new mapping: {platform}:{platform_user_id} -> {unified_id}")
        return unified_id

    def get_platform_user_ids(self, unified_user_id: str) -> Dict[str, str]:
        """Get all platform user IDs for a unified ID

        Args:
            unified_user_id: Unified user ID

        Returns:
            Dictionary mapping platform -> platform_user_id
        """
        mappings = self._load_mappings()
        return mappings.get(unified_user_id, {})

    def link_platform(self, unified_user_id: str, platform: str, platform_user_id: str):
        """Link a platform to an existing unified user ID

        Args:
            unified_user_id: Existing unified user ID
            platform: Platform name
            platform_user_id: Platform-specific user ID
        """
        mappings = self._load_mappings()

        if unified_user_id not in mappings:
            mappings[unified_id] = {}

        mappings[unified_id][platform] = platform_user_id
        self._save_mappings(mappings)

        logger.info(f"Linked platform: {unified_user_id} <- {platform}:{platform_user_id}")

    def unlink_platform(self, unified_user_id: str, platform: str):
        """Unlink a platform from a unified user ID

        Args:
            unified_user_id: Unified user ID
            platform: Platform name
        """
        mappings = self._load_mappings()

        if unified_user_id in mappings and platform in mappings[unified_id]:
            del mappings[unified_id][platform]
            self._save_mappings(mappings)

            logger.info(f"Unlinked platform: {unified_user_id} -> {platform}")

    def get_all_users(self) -> Dict[str, Dict[str, str]]:
        """Get all user mappings

        Returns:
            Dictionary of unified_id -> platform_mappings
        """
        return self._load_mappings()

    def delete_user(self, unified_user_id: str):
        """Delete a unified user

        Args:
            unified_user_id: Unified user ID to delete
        """
        mappings = self._load_mappings()

        if unified_user_id in mappings:
            del mappings[unified_id]
            self._save_mappings(mappings)

            logger.info(f"Deleted user: {unified_user_id}")

    def _save_to_fallback_file(self, mappings: Dict):
        """Save mappings to JSON fallback file (used when Redis fails)"""
        try:
            if hasattr(self, 'fallback_storage_path'):
                with open(self.fallback_storage_path, 'w') as f:
                    json.dump(mappings, f, indent=2)
                logger.debug(f"Saved {len(mappings)} user mappings to fallback file")
        except Exception as e:
            logger.error(f"Error saving to fallback file: {e}")

    def _send_redis_failure_warning(self, error: Exception, operation: str):
        """Send Redis failure warning with deduplication"""

        from datetime import datetime
        now = datetime.now()

        if self._last_redis_failure_time:
            time_since_last = (now - self._last_redis_failure_time).total_seconds()
            if time_since_last < self._redis_failure_cooldown:
                logger.debug(f"Redis failure notification suppressed (cooldown: {self._redis_failure_cooldown - time_since_last:.0f}s remaining)")
                return

        self._last_redis_failure_time = now

        try:
            from notification_system.service import get_notification_service
            import asyncio
            service = get_notification_service()


            async def _send():
                fallback = "JSON fallback file" if hasattr(self, 'fallback_storage_path') else "in-memory"
                await service.send_redis_failure(operation, fallback)

            asyncio.create_task(_send())
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Failed to send Redis failure notification: {e}")
