"""
Unified Messaging Gateway Models

Standardized message formats and data structures for cross-platform messaging.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
import uuid


class Platform(Enum):
    """Supported messaging platforms"""
    TELEGRAM = "telegram"


class MediaType(Enum):
    """Supported media types"""
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"


class DeliveryStatus(Enum):
    """Message delivery status"""
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class MediaAttachment:
    """Media attachment for messages"""
    type: MediaType
    url: str
    mime_type: Optional[str] = None
    caption: Optional[str] = None
    file_size: Optional[int] = None
    thumbnail_url: Optional[str] = None


@dataclass
class UnifiedMessage:
    """Standardized message format across all platforms

    This is the internal representation used by the gateway.
    Platform-specific formats are converted to/from this format.
    """
    id: str
    platform: Platform
    user_id: str
    unified_user_id: Optional[str] = None
    business: str = "yo_bakery"
    content: str = ""
    media: Optional[List[MediaAttachment]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "platform": self.platform.value,
            "user_id": self.user_id,
            "unified_user_id": self.unified_user_id,
            "business": self.business,
            "content": self.content,
            "media": [
                {
                    "type": m.type.value,
                    "url": m.url,
                    "mime_type": m.mime_type,
                    "caption": m.caption,
                    "file_size": m.file_size,
                    "thumbnail_url": m.thumbnail_url
                }
                for m in (self.media or [])
            ],
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UnifiedMessage':
        """Create from dictionary"""
        media_attachments = None
        if data.get("media"):
            media_attachments = [
                MediaAttachment(
                    type=MediaType(m["type"]),
                    url=m["url"],
                    mime_type=m.get("mime_type"),
                    caption=m.get("caption"),
                    file_size=m.get("file_size"),
                    thumbnail_url=m.get("thumbnail_url")
                )
                for m in data["media"]
            ]

        return cls(
            id=data["id"],
            platform=Platform(data["platform"]),
            user_id=data["user_id"],
            unified_user_id=data.get("unified_user_id"),
            business=data.get("business", "yo_bakery"),
            content=data.get("content", ""),
            media=media_attachments,
            metadata=data.get("metadata", {}),
            timestamp=datetime.fromisoformat(data["timestamp"])
        )


@dataclass
class DeliveryInfo:
    """Message delivery tracking information"""
    id: str
    message_id: str
    platform: Platform
    user_id: str
    status: DeliveryStatus
    attempts: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_error: Optional[str] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "message_id": self.message_id,
            "platform": self.platform.value,
            "user_id": self.user_id,
            "status": self.status.value,
            "attempts": self.attempts,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_error": self.last_error,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeliveryInfo':
        """Create from dictionary"""
        return cls(
            id=data["id"],
            message_id=data["message_id"],
            platform=Platform(data["platform"]),
            user_id=data["user_id"],
            status=DeliveryStatus(data["status"]),
            attempts=data.get("attempts", 0),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            last_error=data.get("last_error"),
            sent_at=datetime.fromisoformat(data["sent_at"]) if data.get("sent_at") else None,
            delivered_at=datetime.fromisoformat(data["delivered_at"]) if data.get("delivered_at") else None
        )
