"""
Message Router

Central routing logic for incoming and outgoing messages.
Handles platform-specific routing and user mapping.
"""

import logging
from typing import Dict, Optional, Any
import uuid
import asyncio

from .models import UnifiedMessage, Platform, DeliveryInfo, DeliveryStatus
from .user_mapper import UserMapper
from .adapters.base import PlatformAdapter

logger = logging.getLogger(__name__)


class MessageRouter:
    """Central message router

    Routes incoming messages to appropriate handlers and manages
    outgoing message delivery through platform adapters.
    """

    def __init__(self, user_mapper: UserMapper, lazy_business_loading: bool = False):
        """Initialize message router

        Args:
            user_mapper: UserMapper instance for cross-platform user mapping
            lazy_business_loading: If True, discover and load business engines on-demand
        """
        self.user_mapper = user_mapper
        self.platform_adapters: Dict[str, PlatformAdapter] = {}
        self.business_engines: Dict[str, object] = {}
        self.delivery_trackers = {}
        self.lazy_business_loading = lazy_business_loading


        try:
            from smart_engine.core.business_resolver import BusinessResolver
            self.business_resolver = BusinessResolver()
        except Exception as e:
            logger.warning(f"Could not initialize business resolver: {e}")
            self.business_resolver = None

    def register_adapter(self, platform: str, adapter: PlatformAdapter):
        """Register a platform adapter

        Args:
            platform: Platform name (e.g. telegram)
            adapter: PlatformAdapter instance
        """
        self.platform_adapters[platform] = adapter
        logger.info(f"Registered adapter for platform: {platform}")

    def register_business(self, name: str, engine):
        """Register a business engine

        Args:
            name: Business name
            engine: ChatEngine instance
        """
        self.business_engines[name] = engine
        logger.info(f"Registered business engine: {name}")

    def register_delivery_tracker(self, platform: str, tracker):
        """Register a delivery tracker for a platform

        Args:
            platform: Platform name
            tracker: DeliveryTracker instance
        """
        self.delivery_trackers[platform] = tracker
        logger.info(f"Registered delivery tracker for platform: {platform}")

    def get_adapter(self, platform: str) -> Optional[PlatformAdapter]:
        """Get adapter for a platform

        Args:
            platform: Platform name

        Returns:
            PlatformAdapter instance or None
        """
        return self.platform_adapters.get(platform)

    def get_business_engine(self, name: str):
        """Get business engine by name

        Args:
            name: Business name

        Returns:
            ChatEngine instance or None
        """
        return self.business_engines.get(name)

    async def route_message(self, message: UnifiedMessage, business_name: str = None) -> UnifiedMessage:
        """Route incoming message to appropriate handler

        Args:
            message: Incoming UnifiedMessage
            business_name: Optional pre-resolved business name (for multi-bot support)

        Returns:
            Response UnifiedMessage
        """
        logger.debug(f"Routing message from {message.platform} user {message.user_id}")


        if not message.unified_user_id:
            message.unified_user_id = self.user_mapper.get_or_create(
                platform=message.platform.value,
                platform_user_id=message.user_id
            )


        target_business = business_name or message.business
        engine = self.get_business_engine(target_business)

        if not engine and self.lazy_business_loading and target_business:
            engine = self._lazy_load_business(target_business)

        if not engine and self.business_resolver and message.metadata:
            bot_id = message.metadata.get('bot_id')
            if bot_id:
                resolved_business = self.business_resolver.resolve_business(bot_id)
                if resolved_business:
                    message.business = resolved_business
                    target_business = resolved_business
                    engine = self.get_business_engine(resolved_business)
                    if not engine and self.lazy_business_loading:
                        engine = self._lazy_load_business(resolved_business)

        if not engine:
            logger.warning(f"Business '{message.business}' not found, using default")
            engine = self.get_business_engine("yo_bakery")
            if not engine and self.lazy_business_loading:
                engine = self._lazy_load_business("yo_bakery")
            if not engine:
                raise ValueError(f"No business engine available for '{message.business}'")


        try:
            reply = engine.process_message(message.content, message.unified_user_id)


            metadata = getattr(reply, 'meta', {})

            if message.metadata:
                metadata['chat_id'] = message.metadata.get('chat_id')
                metadata['chat_type'] = message.metadata.get('chat_type')

            response = UnifiedMessage(
                id=str(uuid.uuid4()),
                platform=message.platform,
                user_id=message.user_id,
                unified_user_id=message.unified_user_id,
                business=message.business,
                content=reply.text,
                metadata=metadata
            )

            logger.debug(f"Generated response for {message.platform} user {message.user_id}")
            return response

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            raise

    async def _capture_chat_id_for_notifications(self, message: UnifiedMessage):
        """Auto-capture chat ID for notification recipients if not already registered.

        This allows business owners to message the bot and automatically receive notifications.
        """
        if message.platform != Platform.TELEGRAM:
            return

        chat_id = message.metadata.get('chat_id') if message.metadata else None
        if not chat_id:
            return

        try:
            from notification_system.service import get_notification_service
            from notification_system.chat_id_store import RecipientType

            service = get_notification_service()


            existing_ids = service.storage.get_chat_ids(
                recipient_type=RecipientType.BUSINESS_OWNER,
                business_name=message.business
            )

            if str(chat_id) not in [str(cid) for cid in existing_ids]:

                user_name = None
                raw_message = message.metadata.get('raw_message', {})
                from_user = raw_message.get('from', {})
                first_name = from_user.get('first_name', '')
                last_name = from_user.get('last_name', '')
                username = from_user.get('username', '')

                if first_name or last_name:
                    user_name = f"{first_name} {last_name}".strip()
                elif username:
                    user_name = f"@{username}"
                else:
                    user_name = f"User {chat_id}"


                service.storage.register_chat_id(
                    chat_id=str(chat_id),
                    recipient_type=RecipientType.BUSINESS_OWNER,
                    business_name=message.business,
                    user_name=user_name
                )
                logger.debug(f"Auto-captured chat ID {chat_id} for business '{message.business}' notifications")
        except ImportError:

            pass
        except Exception as e:
            logger.debug(f"Could not auto-capture chat ID: {e}")

    async def send_message(self, message: UnifiedMessage, bot_token: str = None) -> DeliveryInfo:
        """Send message through appropriate platform adapter

        Args:
            message: UnifiedMessage to send
            bot_token: Optional bot token for multi-bot Telegram support

        Returns:
            DeliveryInfo with status
        """
        logger.debug(f"Sending message to {message.platform} user {message.user_id}")


        platform = message.platform.value
        adapter = self.get_adapter(platform)


        if bot_token and platform == "telegram":
            adapter = self._get_telegram_adapter_for_bot(bot_token)

        if not adapter:
            logger.error(f"No adapter found for platform: {platform}")
            delivery_info = DeliveryInfo(
                id=str(uuid.uuid4()),
                message_id=message.id,
                platform=message.platform,
                user_id=message.user_id,
                status=DeliveryStatus.FAILED,
                last_error="No adapter found for platform"
            )
            return delivery_info


        tracker = self.delivery_trackers.get(platform)
        delivery_id = None
        if tracker:
            delivery_id = await tracker.track_message(message)


        try:
            delivery_info = await adapter.send_message(message)


            if tracker and delivery_id:
                await tracker.update_status(
                    delivery_id,
                    delivery_info.status,
                    delivery_info.last_error
                )

            logger.debug(f"Message sent with status: {delivery_info.status.value}")
            return delivery_info

        except Exception as e:
            logger.error(f"Error sending message: {e}", exc_info=True)


            if tracker and delivery_id:
                await tracker.update_status(
                    delivery_id,
                    DeliveryStatus.FAILED,
                    str(e)
                )

            raise

    def _get_telegram_adapter_for_bot(self, bot_token: str) -> Optional[PlatformAdapter]:
        """Get or create a Telegram adapter for a specific bot token.

        For multi-bot support, each bot needs its own adapter with its own token.

        Args:
            bot_token: The Telegram bot token

        Returns:
            TelegramAdapter instance for the bot
        """

        adapter_key = f"telegram_{bot_token}"
        if adapter_key in self.platform_adapters:
            return self.platform_adapters[adapter_key]


        try:
            from unified_gateway.adapters.telegram import TelegramAdapter
            from unified_gateway.config import PlatformConfig

            config = PlatformConfig(
                enabled=True,
                bot_token=bot_token,
                api_url=f"https://api.telegram.org/bot{bot_token}"
            )

            adapter = TelegramAdapter(config)
            self.platform_adapters[adapter_key] = adapter
            logger.debug(f"Created Telegram adapter for bot token: {bot_token[:10]}...")
            return adapter

        except Exception as e:
            logger.error(f"Failed to create Telegram adapter for bot: {e}")
            return None

    def _lazy_load_business(self, business_name: str):
        """Lazily load a business engine on-demand."""
        if business_name in self.business_engines:
            return self.business_engines[business_name]

        try:
            from smart_engine.core.chat_engine import ChatEngine
            engine = ChatEngine(business_name)
            self.register_business(business_name, engine)
            return engine
        except Exception as e:
            logger.warning(f"Failed to lazy load business '{business_name}': {e}")
            return None

    async def handle_webhook(self, platform: str, headers: Dict, body: Any,
                             bot_token: str = None, business_name: str = None) -> UnifiedMessage:
        """Handle webhook from platform

        Args:
            platform: Platform name
            headers: HTTP headers
            body: Request body
            bot_token: Bot token for multi-bot Telegram support
            business_name: Pre-resolved business name for multi-bot support

        Returns:
            Response message to send back
        """
        logger.debug(f"Handling webhook from {platform}" + (f" for business '{business_name}'" if business_name else ""))


        adapter = None
        if bot_token and platform == "telegram":

            adapter = self._get_telegram_adapter_for_bot(bot_token)
            if not adapter:
                raise ValueError(f"No adapter found for bot token: {bot_token[:10]}...")


        if not adapter:
            adapter = self.get_adapter(platform)
            if not adapter:
                raise ValueError(f"No adapter found for platform: {platform}")


        if not await adapter.verify_webhook(headers, body):
            logger.warning(f"Webhook verification failed for {platform}")
            raise ValueError("Invalid webhook")


        message = await adapter.receive_message(body, bot_token=bot_token)


        if business_name:
            message.business = business_name


        response = await self.route_message(message, business_name=business_name)


        if business_name:
            response.business = business_name


        await self._capture_chat_id_for_notifications(message)


        await self.send_message(response, bot_token=bot_token)

        return response

    def get_status(self) -> Dict:
        """Get router status

        Returns:
            Dictionary with router status
        """
        return {
            "platforms": list(self.platform_adapters.keys()),
            "businesses": list(self.business_engines.keys()),
            "delivery_trackers": list(self.delivery_trackers.keys())
        }
