"""
Data models for notifications with clean formatting
"""
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid
import re


from .chat_id_store import RecipientType as NotificationRole

class NotificationPriority(Enum):
    """How important is it"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class Notification:
    """A notification message"""
    title: str
    message: str
    role: NotificationRole
    priority: NotificationPriority = NotificationPriority.MEDIUM
    business_name: Optional[str] = None
    source: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    @classmethod
    def create(cls, **kwargs) -> 'Notification':
        """Create a notification with defaults"""
        return cls(**kwargs)

    def format_for_telegram(self) -> str:
        """Format for Telegram using HTML (simpler than Markdown)"""
        priority_icons = {
            NotificationPriority.CRITICAL: "CRITICAL",
            NotificationPriority.HIGH: "HIGH",
            NotificationPriority.MEDIUM: "MEDIUM",
            NotificationPriority.LOW: "INFO",
        }

        icon = priority_icons.get(self.priority, "INFO")


        lines = []


        # Escape title (may contain special chars); message is already HTML-formatted
        lines.append(f"<b>[{icon}] {self._escape_html(self.title)}</b>")
        lines.append("")


        lines.append(self.message)
        lines.append("")


        lines.append(f"<b>Time:</b> {self.timestamp.strftime('%H:%M:%S')}")
        lines.append(f"<b>Date:</b> {self.timestamp.strftime('%Y-%m-%d')}")

        return "\n".join([line for line in lines if line is not None])

    def _escape_html(self, text: str) -> str:
        """Simple HTML escaping for Telegram"""
        if not text:
            return ""


        return (
            text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
        )
