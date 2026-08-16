"""
Platform Adapter Base Interface

Abstract base class for all platform adapters.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging
from ..models import UnifiedMessage, DeliveryInfo, DeliveryStatus

logger = logging.getLogger(__name__)


class PlatformAdapter(ABC):
    """Base class for all platform adapters

    This abstract class defines the interface that all platform adapters
    must implement. Each adapter handles platform-specific message format
    conversion and communication.
    """

    def __init__(self, config):
        """Initialize adapter with configuration

        Args:
            config: PlatformConfig instance
        """
        self.config = config
        self.platform_name = None
        self.enabled = config.enabled if hasattr(config, 'enabled') else False

    @abstractmethod
    async def receive_message(self, raw_data: Any) -> UnifiedMessage:
        """Convert platform-specific message to UnifiedMessage

        Args:
            raw_data: Raw message data from platform (JSON, form data, etc.)

        Returns:
            UnifiedMessage instance
        """
        pass

    @abstractmethod
    async def send_message(self, message: UnifiedMessage) -> DeliveryInfo:
        """Send UnifiedMessage to platform

        Args:
            message: UnifiedMessage to send

        Returns:
            DeliveryInfo with status tracking
        """
        pass

    @abstractmethod
    async def setup_webhook(self, webhook_url: str) -> bool:
        """Configure platform webhook

        Args:
            webhook_url: URL to receive webhooks

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    async def verify_webhook(self, headers: Dict, body: Any) -> bool:
        """Verify webhook authenticity

        Args:
            headers: HTTP headers from webhook request
            body: Raw webhook body

        Returns:
            True if webhook is authentic, False otherwise
        """
        pass

    @abstractmethod
    def format_message(self, text: str) -> str:
        """Format text for platform-specific syntax

        Converts unified text format to platform-specific formatting
        (e.g., Markdown for Telegram)

        Args:
            text: Unified text content

        Returns:
            Platform-formatted text
        """
        pass

    def convert_to_unified(self, raw_data: Dict[str, Any], platform: str, 
                          user_id: str, business: str = "yo_bakery") -> UnifiedMessage:
        """Helper method to convert common webhook data to UnifiedMessage

        Args:
            raw_data: Raw webhook data
            platform: Platform name (e.g. telegram)
            user_id: Platform-specific user ID
            business: Business name

        Returns:
            UnifiedMessage instance
        """
        import uuid
        from datetime import datetime

        return UnifiedMessage(
            id=str(uuid.uuid4()),
            platform=platform,
            user_id=user_id,
            business=business,
            content=raw_data.get("text", raw_data.get("content", "")),
            metadata=raw_data
        )

    def create_delivery_info(self, message: UnifiedMessage, 
                             status: DeliveryStatus = DeliveryStatus.PENDING) -> DeliveryInfo:
        """Helper method to create DeliveryInfo

        Args:
            message: UnifiedMessage being tracked
            status: Initial delivery status

        Returns:
            DeliveryInfo instance
        """
        import uuid

        return DeliveryInfo(
            id=str(uuid.uuid4()),
            message_id=message.id,
            platform=message.platform,
            user_id=message.user_id,
            status=status
        )
