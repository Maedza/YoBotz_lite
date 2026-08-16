"""
Chat ID Storage for persistent notification targets
Uses TimezoneService for consistent timezone handling
"""
import json
import logging
from typing import Dict, List, Optional
from pathlib import Path
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


def _get_utc_now() -> datetime:
    """Get current time in UTC for storage"""
    try:
        from smart_engine.core.timezone_service import TimezoneService
        return TimezoneService.now_utc()
    except (ImportError, Exception):

        import pytz
        return datetime.now(pytz.UTC)

logger = logging.getLogger(__name__)


class RecipientType(Enum):
    BUSINESS_OWNER = "business_owner"
    DEVELOPER = "developer"
    SYSTEM_ADMIN = "system_admin"


class ChatIDStorage:
    """Persistent storage for Telegram chat IDs"""

    def __init__(self, storage_path: str = "data/notification_chat_ids.json"):
        self.storage_path = Path(storage_path)
        self._ensure_storage()

    def _ensure_storage(self):
        """Ensure storage file exists"""
        self.storage_path.parent.mkdir(exist_ok=True, parents=True)
        if not self.storage_path.exists():
            with open(self.storage_path, 'w') as f:
                json.dump({
                    "business_owners": {},
                    "developers": [],
                    "system_admins": []
                }, f, indent=2)
            logger.debug(f"Created new chat ID storage at {self.storage_path}")

    def load(self) -> Dict:
        """Load chat IDs from storage"""
        try:
            with open(self.storage_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load chat IDs: {e}")
            return {"business_owners": {}, "developers": [], "system_admins": []}

    def save(self, data: Dict):
        """Save chat IDs to storage"""
        try:
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save chat IDs: {e}")

    def register_chat_id(
        self,
        chat_id: str,
        recipient_type: RecipientType,
        business_name: Optional[str] = None,
        user_name: Optional[str] = None
    ) -> bool:
        """Register a chat ID for notifications"""
        data = self.load()

        if recipient_type == RecipientType.BUSINESS_OWNER:
            if not business_name:
                logger.error(
                    "Business name required for business owner registration")
                return False

            if business_name not in data["business_owners"]:
                data["business_owners"][business_name] = []


            existing_ids = [c["chat_id"]
                            for c in data["business_owners"][business_name]]
            if chat_id not in existing_ids:
                data["business_owners"][business_name].append({
                    "chat_id": chat_id,
                    "user_name": user_name,
                    "registered_at": _get_utc_now().isoformat() + "Z"
                })
                self.save(data)
                logger.debug(f"Registered business owner: {business_name} - {user_name}")
                return True
            else:
                logger.debug(f"Chat ID already registered for business: {business_name}")
                return True

        elif recipient_type == RecipientType.DEVELOPER:
            existing_ids = [c["chat_id"] for c in data["developers"]]
            if chat_id not in existing_ids:
                data["developers"].append({
                    "chat_id": chat_id,
                    "user_name": user_name,
                    "registered_at": _get_utc_now().isoformat() + "Z"
                })
                self.save(data)
                logger.debug(f"Registered developer: {user_name}")
                return True

        elif recipient_type == RecipientType.SYSTEM_ADMIN:
            existing_ids = [c["chat_id"] for c in data["system_admins"]]
            if chat_id not in existing_ids:
                data["system_admins"].append({
                    "chat_id": chat_id,
                    "user_name": user_name,
                    "registered_at": _get_utc_now().isoformat() + "Z"
                })
                self.save(data)
                logger.debug(f"Registered system admin: {user_name}")
                return True

        return False

    def get_chat_ids(self, recipient_type: RecipientType, business_name: Optional[str] = None) -> List[str]:
        """Get chat IDs for notification recipients"""
        data = self.load()

        if recipient_type == RecipientType.BUSINESS_OWNER and business_name:
            return [c["chat_id"] for c in data["business_owners"].get(business_name, [])]

        elif recipient_type == RecipientType.DEVELOPER:
            return [c["chat_id"] for c in data["developers"]]

        elif recipient_type == RecipientType.SYSTEM_ADMIN:
            return [c["chat_id"] for c in data["system_admins"]]

        return []

    def get_all_recipients(self) -> Dict:
        """Get all registered recipients"""
        return self.load()

    def remove_chat_id(self, chat_id: str) -> bool:
        """Remove a chat ID from all categories"""
        data = self.load()
        removed = False


        for business in list(data["business_owners"].keys()):
            data["business_owners"][business] = [
                c for c in data["business_owners"][business]
                if c["chat_id"] != chat_id
            ]

            if not data["business_owners"][business]:
                del data["business_owners"][business]
                removed = True


        original_dev_count = len(data["developers"])
        data["developers"] = [
            c for c in data["developers"] if c["chat_id"] != chat_id]
        if len(data["developers"]) < original_dev_count:
            removed = True


        original_admin_count = len(data["system_admins"])
        data["system_admins"] = [
            c for c in data["system_admins"] if c["chat_id"] != chat_id]
        if len(data["system_admins"]) < original_admin_count:
            removed = True

        if removed:
            self.save(data)
            logger.debug(f"Removed chat ID: {chat_id}")

        return removed


class InMemoryChatIDStorage(ChatIDStorage):
    """In-memory storage for Telegram chat IDs"""

    def __init__(self):
        # Don't call parent __init__ to avoid file operations
        self.storage = self.data = {
            "business_owners": {},
            "developers": [],
            "system_admins": []
        }

    def load(self) -> Dict:
        """Load chat IDs from in-memory storage"""
        return self.data

    def save(self, data: Dict):
        """Save chat IDs to in-memory storage"""
        self.data = data

    def get_chat_ids(self, recipient_type, business_name: Optional[str] = None) -> List[str]:
        """Get chat IDs for notification recipients - accepts both Enum and string"""

        if isinstance(recipient_type, str):
            try:
                recipient_type = RecipientType(recipient_type.lower())
            except ValueError:
                return []

        data = self.load()

        if recipient_type == RecipientType.BUSINESS_OWNER and business_name:
            return [c["chat_id"] for c in data["business_owners"].get(business_name, [])]

        elif recipient_type == RecipientType.DEVELOPER:
            return [c["chat_id"] for c in data["developers"]]

        elif recipient_type == RecipientType.SYSTEM_ADMIN:
            return [c["chat_id"] for c in data["system_admins"]]

        return []
