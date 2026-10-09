"""
Main notification service with dependency injection
"""
import os
import logging
import yaml
from typing import Dict, Optional
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
import threading
import requests


load_dotenv()

from .models import Notification, NotificationPriority
from .telegram_notifier import TelegramNotifier
from .chat_id_store import ChatIDStorage, RecipientType as NotificationRole
from .token_registry import TokenRegistry

logger = logging.getLogger(__name__)


@dataclass
class NotificationConfig:
    """Notification configuration"""
    telegram_enabled: bool = True
    email_enabled: bool = False
    telegram_bot_token: Optional[str] = None
    email_settings: Optional[Dict] = None


class NotificationService:
    """Orchestrates notification delivery"""

    def __init__(self, config: Optional[NotificationConfig] = None):
        self.config = config or self._load_config()
        self.telegram_notifier: Optional[TelegramNotifier] = None


        self.storage = ChatIDStorage(storage_path="data/notification_chat_ids.json")
        self._load_env_chat_ids()


        self.token_registry = TokenRegistry()

        logger.info("Using persistent ChatIDStorage: data/notification_chat_ids.json")
        logger.info("TokenRegistry initialized for multi-business support")

        self._initialize_channels()

    def _load_config(self) -> NotificationConfig:
        """Load configuration from YAML"""
        config_path = Path("data/configs/notification_config.yaml")


        telegram_bot_token = os.getenv("NOTIFICATION_BOT_TOKEN")
        telegram_enabled = bool(telegram_bot_token)


        if not telegram_bot_token and config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config_data = yaml.safe_load(f) or {}

                channels = config_data.get('channels', {})
                telegram_config = channels.get('telegram', {})


                telegram_bot_token = telegram_config.get('settings', {}).get('bot_token')
                telegram_enabled = telegram_config.get('enabled', False)

                logger.info(f"Loaded notification config from file: telegram_enabled={telegram_enabled}")
            except Exception as e:
                logger.warning(f"Failed to load notification config: {e}")

        if telegram_bot_token:
            logger.info(f"Notification bot token configured: {telegram_bot_token[:20]}...")
        else:
            logger.warning("No notification bot token found in environment or config file")

        return NotificationConfig(
            telegram_enabled=telegram_enabled,
            telegram_bot_token=telegram_bot_token
        )

    def _load_env_chat_ids(self):
        """Load developer chat ID from root env + business owner chat IDs from vaults."""
        developer_chat_id = os.getenv('DEVELOPER_CHAT_ID')

        if developer_chat_id:
            from .chat_id_store import RecipientType
            try:
                self.storage.register_chat_id(
                    chat_id=str(developer_chat_id),
                    recipient_type=RecipientType.DEVELOPER,
                    user_name="Developer (from .env)"
                )
                logger.info(f"Loaded developer chat ID from .env: {developer_chat_id}")
            except Exception as e:
                logger.warning(f"Failed to register developer chat ID: {e}")

        try:
            from core.business_registry import BusinessRegistry
            registry = BusinessRegistry()
            for biz_name in registry.list_businesses():
                vault = registry.get_vault(biz_name)
                if not vault:
                    continue
                owner_id = vault.business_owner_chat_id
                if owner_id:
                    try:
                        self.storage.register_chat_id(
                            chat_id=str(owner_id),
                            recipient_type=RecipientType.BUSINESS_OWNER,
                            business_name=biz_name,
                            user_name=f"Business Owner (from vault: {biz_name})"
                        )
                        logger.info(f"Loaded business owner chat ID for '{biz_name}' from vault")
                    except Exception as e:
                        logger.warning(f"Failed to register chat ID for '{biz_name}': {e}")
        except Exception as e:
            logger.warning(f"Failed to load per-business chat IDs from vaults: {e}")

    def _initialize_channels(self):
        """Initialize notification channels"""
        if self.config.telegram_enabled and self.config.telegram_bot_token:
            try:
                self.telegram_notifier = TelegramNotifier(
                    self.config.telegram_bot_token,
                    storage=self.storage
                )
                logger.info("Telegram notifier initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Telegram notifier: {e}")
                self.telegram_notifier = None

    def _send_telegram_sync(self, chat_id: str, message: str, disable_notification: bool = False, business_name: Optional[str] = None) -> bool:
        """Send message to Telegram using synchronous requests library"""

        bot_token = self.token_registry.get_token(business_name)

        if not bot_token:
            logger.error(f"[SYNC] No Telegram bot token configured for business: {business_name}")
            return False

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_notification": disable_notification,
            "disable_web_page_preview": True,
        }

        logger.info(f"[SYNC] Sending notification to chat {chat_id} for business: {business_name or 'default'}")

        for attempt in range(3):
            try:
                response = requests.post(url, json=payload, timeout=30)
                logger.info(f"[SYNC] Attempt {attempt+1}: HTTP {response.status_code}")

                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        logger.info(f"[SYNC] ✅ Successfully sent to {chat_id}")
                        return True
                    else:
                        logger.error(f"[SYNC] ❌ Telegram API error: {data}")
                else:
                    logger.error(f"[SYNC] ❌ HTTP {response.status_code}: {response.text}")
            except requests.exceptions.Timeout:
                logger.warning(f"[SYNC] ⏱️ Timeout sending to {chat_id}, attempt {attempt + 1} (network issue?)")
            except requests.exceptions.ConnectionError as e:
                logger.error(f"[SYNC] 🔌 Connection error to {chat_id}, attempt {attempt + 1}: {e} (check network/VPN)")
            except Exception as e:
                logger.error(f"[SYNC] ❌ Error sending to {chat_id}, attempt {attempt + 1}: {e}", exc_info=True)

            if attempt < 2:
                import time
                time.sleep(2 ** attempt)

        logger.error(f"[SYNC] ❌ Failed to send to {chat_id} after 3 attempts (likely network connectivity issue)")
        return False

    async def send_notification(self, notification: Notification) -> bool:
        """Send notification through appropriate channels"""

        if not notification.title or not notification.message:
            logger.error("Notification missing title or message")
            return False


        bot_token = self.token_registry.get_token(notification.business_name)
        if not bot_token:
            logger.warning(f"No bot token available for business: {notification.business_name}")
            return False


        try:
            notifier = TelegramNotifier(bot_token, storage=self.storage)
            return await notifier.send_notification(notification)
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")
            return False

        logger.warning("No notification channels available")
        return False


    async def send_business_alert(
        self,
        business_name: str,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        source: Optional[str] = None
    ) -> bool:
        """Send business alert to business owners"""
        notification = Notification.create(
            title=title,
            message=message,
            role=NotificationRole.BUSINESS_OWNER,
            priority=priority,
            business_name=business_name,
            source=source or "business_alert"
        )

        return await self.send_notification(notification)

    async def send_system_alert(
        self,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        source: Optional[str] = None
    ) -> bool:
        """Send system alert to developers"""
        notification = Notification.create(
            title=title,
            message=message,
            role=NotificationRole.DEVELOPER,
            priority=priority,
            source=source or "system_alert"
        )

        return await self.send_notification(notification)

    async def send_admin_alert(
        self,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.HIGH,
        source: Optional[str] = None
    ) -> bool:
        """Send admin alert to system admins"""
        notification = Notification.create(
            title=title,
            message=message,
            role=NotificationRole.SYSTEM_ADMIN,
            priority=priority,
            source=source or "admin_alert"
        )

        return await self.send_notification(notification)

    async def send_server_started(self, business_name: str = None) -> bool:
        """Send notification when server starts"""
        notification = Notification.create(
            title="Gateway Server Started",
            message=f"The unified gateway server has started successfully.\nBusiness: {business_name or 'Default'}",
            role=NotificationRole.DEVELOPER,
            priority=NotificationPriority.LOW,
            source="gateway_startup",
            business_name=business_name
        )

        return await self.send_notification(notification)

    async def send_error_notification(
        self,
        error_type: str,
        error_message: str,
        context: Optional[str] = None
    ) -> bool:
        """Send error notification to developers"""
        message = f"Type: {error_type}\n"
        if context:
            message += f"Context: {context}\n"
        message += f"Error: {error_message}"

        notification = Notification.create(
            title=f"Error: {error_type}",
            message=message,
            role=NotificationRole.DEVELOPER,
            priority=NotificationPriority.HIGH,
            source="error_handler"
        )

        return await self.send_notification(notification)

    async def send_webhook_failure(
        self,
        platform: str,
        reason: str,
        payload_summary: Optional[str] = None
    ) -> bool:
        """Send notification when webhook fails"""
        message = f"Platform: {platform}\nReason: {reason}"
        if payload_summary:
            message += f"\nPayload: {payload_summary}"

        notification = Notification.create(
            title=f"Webhook Failed: {platform}",
            message=message,
            role=NotificationRole.DEVELOPER,
            priority=NotificationPriority.HIGH,
            source="webhook_error"
        )

        return await self.send_notification(notification)

    async def send_delivery_failure(
        self,
        platform: str,
        recipient: str,
        reason: str,
        retry_count: int = 0
    ) -> bool:
        """Send notification when message delivery fails"""
        message = f"Platform: {platform}\nRecipient: {recipient}\nReason: {reason}\nRetry Count: {retry_count}"

        notification = Notification.create(
            title=f"Delivery Failed: {platform}",
            message=message,
            role=NotificationRole.DEVELOPER,
            priority=NotificationPriority.MEDIUM,
            source="delivery_tracker"
        )

        return await self.send_notification(notification)

    async def send_redis_failure(
        self,
        operation: str,
        fallback_used: str
    ) -> bool:
        """Send notification when Redis fails"""
        message = f"Operation: {operation}\nFallback: {fallback_used}\nThe system will continue using the fallback storage."

        notification = Notification.create(
            title="Redis Connection Failed",
            message=message,
            role=NotificationRole.DEVELOPER,
            priority=NotificationPriority.MEDIUM,
            source="redis_handler"
        )

        return await self.send_notification(notification)

    async def send_network_status_change(
        self,
        platform: str,
        status: str,
        details: Optional[str] = None
    ) -> bool:
        """Send notification when network status changes"""
        message = f"Platform: {platform}\nStatus: {status}"
        if details:
            message += f"\nDetails: {details}"

        notification = Notification.create(
            title=f"Network Status: {platform}",
            message=message,
            role=NotificationRole.DEVELOPER,
            priority=NotificationPriority.MEDIUM,
            source="adapter_monitoring"
        )

        return await self.send_notification(notification)

    async def send_message_queue_status(
        self,
        queue_size: int,
        platform: Optional[str] = None
    ) -> bool:
        """Send notification when message queue size is large"""
        message = f"Queue Size: {queue_size}\n"
        if platform:
            message += f"Platform: {platform}\n"
        message += "Consider checking system performance."

        notification = Notification.create(
            title="Message Queue Alert",
            message=message,
            role=NotificationRole.DEVELOPER,
            priority=NotificationPriority.MEDIUM,
            source="message_queue"
        )

        return await self.send_notification(notification)

    async def send_order_created(
        self,
        business_name: str,
        order_data: dict
    ) -> bool:
        """Send notification when order is created"""
        items = order_data.get("items", [])
        items_text = "\n".join([
            f"- {item.get('name', 'Unknown')} x{item.get('quantity', 1)} @ ${float(item.get('price', 0)):.2f}"
            for item in items
        ])

        message = f"Order ID: {order_data.get('order_id', 'N/A')}\n"
        message += f"Customer: {order_data.get('customer_name', 'N/A')}\n"
        total_amount = order_data.get('total_amount', 0)
        if isinstance(total_amount, str):
            try:
                total_amount = float(total_amount)
            except:
                total_amount = 0.0
        message += f"Total: ${float(total_amount):.2f}\n"
        message += "\nItems:\n" + items_text
        message += f"\nTime: {order_data.get('timestamp', 'N/A')}"

        notification = Notification.create(
            title="New Order Created",
            message=message,
            role=NotificationRole.BUSINESS_OWNER,
            priority=NotificationPriority.HIGH,
            source="order_system",
            business_name=business_name
        )

        return await self.send_notification(notification)

    def send_order_created_sync(
        self,
        business_name: str,
        order_data: dict
    ) -> None:
        """Send order notification from synchronous context (runs in background thread)"""
        from .models import Notification, NotificationPriority

        items = order_data.get("items", [])
        items_text = "\n".join([
            f"- {item.get('name', 'Unknown')} x{item.get('quantity', 1)} @ ${float(item.get('price', 0)):.2f}"
            for item in items
        ])

        message = f"Order ID: {order_data.get('order_id', 'N/A')}\n"
        message += f"Customer: {order_data.get('customer_name', 'N/A')}\n"
        total_amount = order_data.get('total_amount', 0)
        if isinstance(total_amount, str):
            try:
                total_amount = float(total_amount)
            except:
                total_amount = 0.0
        message += f"Total: ${float(total_amount):.2f}\n"
        message += "\nItems:\n" + items_text
        message += f"\nTime: {order_data.get('timestamp', 'N/A')}"

        notification = Notification.create(
            title="New Order Created",
            message=message,
            role=NotificationRole.BUSINESS_OWNER,
            priority=NotificationPriority.HIGH,
            source="order_system",
            business_name=business_name
        )

        def _send():
            try:
                chat_ids = self.storage.get_chat_ids(NotificationRole.BUSINESS_OWNER, business_name)
                logger.info(f"[SYNC] Found {len(chat_ids)} chat IDs for {business_name} business owner")

                if not chat_ids:
                    logger.warning(f"[SYNC] No chat IDs found for business owner: {business_name}")
                    return

                success_count = 0
                for chat_id in chat_ids:
                    result = self._send_telegram_sync(chat_id, notification.format_for_telegram(), business_name=business_name)
                    if result:
                        success_count += 1
                    else:
                        logger.warning(f"[SYNC] Failed to send to chat_id {chat_id}")

                logger.info(f"[SYNC] Sent order notification to {success_count}/{len(chat_ids)} recipients")
            except Exception as e:
                logger.error(f"[SYNC] Error sending order notification: {e}", exc_info=True)

        thread = threading.Thread(target=_send, daemon=True)
        thread.start()

    async def send_booking_created(
        self,
        business_name: str,
        booking_data: dict
    ) -> bool:
        """Send notification when booking is created"""
        message = f"Customer: {booking_data.get('customer_name', 'N/A')}\n"
        message += f"Service: {booking_data.get('service_name', 'N/A')}\n"
        message += f"Date: {booking_data.get('booking_date', 'N/A')}\n"
        message += f"Time: {booking_data.get('booking_time', 'N/A')}\n"
        message += f"Party Size: {booking_data.get('party_size', 'N/A')}\n"
        message += f"Contact: {booking_data.get('contact_info', 'N/A')}"

        notification = Notification.create(
            title="New Booking Created",
            message=message,
            role=NotificationRole.BUSINESS_OWNER,
            priority=NotificationPriority.HIGH,
            source="booking_system",
            business_name=business_name
        )

        return await self.send_notification(notification)

    def send_booking_created_sync(
        self,
        business_name: str,
        booking_data: dict
    ) -> None:
        """Send booking notification from synchronous context (runs in background thread)"""

        datetime_str = booking_data.get('datetime_display', booking_data.get('datetime', 'N/A'))


        booking_date = datetime_str
        booking_time = datetime_str


        if datetime_str and datetime_str != 'N/A':
            try:
                from datetime import datetime as dt

                parsed = dt.fromisoformat(datetime_str.replace('Z', '+00:00'))
                booking_date = parsed.strftime('%Y-%m-%d')
                booking_time = parsed.strftime('%H:%M')
            except:
                pass

        message = f"Customer: {booking_data.get('customer_name', 'N/A')}\n"
        message += f"Service: {booking_data.get('service_name', 'N/A')}\n"
        message += f"Date: {booking_data.get('booking_date', booking_date)}\n"
        message += f"Time: {booking_data.get('booking_time', booking_time)}\n"
        message += f"Party Size: {booking_data.get('party_size', 'N/A')}\n"
        message += f"Contact: {booking_data.get('contact_info', 'N/A')}"

        notification = Notification.create(
            title="New Booking Created",
            message=message,
            role=NotificationRole.BUSINESS_OWNER,
            priority=NotificationPriority.HIGH,
            source="booking_system",
            business_name=business_name
        )

        def _send():
            try:
                chat_ids = self.storage.get_chat_ids(NotificationRole.BUSINESS_OWNER, business_name)
                logger.info(f"[SYNC] Found {len(chat_ids)} chat IDs for {business_name} business owner")

                if not chat_ids:
                    logger.warning(f"[SYNC] No chat IDs found for business owner: {business_name}")
                    return

                success_count = 0
                for chat_id in chat_ids:
                    result = self._send_telegram_sync(chat_id, notification.format_for_telegram(), business_name=business_name)
                    if result:
                        success_count += 1
                    else:
                        logger.warning(f"[SYNC] Failed to send to chat_id {chat_id}")

                logger.info(f"[SYNC] Sent booking notification to {success_count}/{len(chat_ids)} recipients")
            except Exception as e:
                logger.error(f"[SYNC] Error sending booking notification: {e}", exc_info=True)

        thread = threading.Thread(target=_send, daemon=True)
        thread.start()

    async def send_booking_cancelled(
        self,
        business_name: str,
        booking_data: dict
    ) -> bool:
        """Send notification when booking is cancelled"""
        message = f"Customer: {booking_data.get('customer_name', 'N/A')}\n"
        message += f"Service: {booking_data.get('service_name', 'N/A')}\n"
        message += f"Date: {booking_data.get('booking_date', 'N/A')}\n"
        message += f"Time: {booking_data.get('booking_time', 'N/A')}\n"
        message += f"Party Size: {booking_data.get('party_size', 'N/A')}\n"
        message += f"Contact: {booking_data.get('contact_info', 'N/A')}\n"
        message += f"\nReason: {booking_data.get('cancellation_reason', 'Not specified')}"

        notification = Notification.create(
            title="Booking Cancelled",
            message=message,
            role=NotificationRole.BUSINESS_OWNER,
            priority=NotificationPriority.MEDIUM,
            source="booking_system",
            business_name=business_name
        )

        return await self.send_notification(notification)

    def send_booking_cancelled_sync(
        self,
        business_name: str,
        booking_data: dict
    ) -> None:
        """Send booking cancellation notification from synchronous context (runs in background thread)"""

        datetime_str = booking_data.get('datetime_display', booking_data.get('datetime', 'N/A'))


        booking_date = datetime_str
        booking_time = datetime_str


        if datetime_str and datetime_str != 'N/A':
            try:
                from datetime import datetime as dt

                parsed = dt.fromisoformat(datetime_str.replace('Z', '+00:00'))
                booking_date = parsed.strftime('%Y-%m-%d')
                booking_time = parsed.strftime('%H:%M')
            except:
                pass

        message = f"Customer: {booking_data.get('customer_name', 'N/A')}\n"
        message += f"Service: {booking_data.get('service_name', 'N/A')}\n"
        message += f"Date: {booking_data.get('booking_date', booking_date)}\n"
        message += f"Time: {booking_data.get('booking_time', booking_time)}\n"
        message += f"Party Size: {booking_data.get('party_size', 'N/A')}\n"
        message += f"Contact: {booking_data.get('contact_info', 'N/A')}\n"
        message += f"\nReason: {booking_data.get('cancellation_reason', 'User cancelled')}"

        notification = Notification.create(
            title="Booking Cancelled",
            message=message,
            role=NotificationRole.BUSINESS_OWNER,
            priority=NotificationPriority.MEDIUM,
            source="booking_system",
            business_name=business_name
        )

        def _send():
            try:
                chat_ids = self.storage.get_chat_ids(NotificationRole.BUSINESS_OWNER, business_name)
                logger.info(f"[SYNC] Found {len(chat_ids)} chat IDs for {business_name} business owner")

                if not chat_ids:
                    logger.warning(f"[SYNC] No chat IDs found for business owner: {business_name}")
                    return

                success_count = 0
                for chat_id in chat_ids:
                    result = self._send_telegram_sync(chat_id, notification.format_for_telegram(), business_name=business_name)
                    if result:
                        success_count += 1
                    else:
                        logger.warning(f"[SYNC] Failed to send to chat_id {chat_id}")

                logger.info(f"[SYNC] Sent booking cancellation notification to {success_count}/{len(chat_ids)} recipients")
            except Exception as e:
                logger.error(f"[SYNC] Error sending booking cancellation notification: {e}", exc_info=True)

        thread = threading.Thread(target=_send, daemon=True)
        thread.start()

    async def send_daily_summary(
        self,
        business_name: str,
        metrics: dict
    ) -> bool:
        """Send daily business summary notification"""
        from .templates import NotificationTemplates
        from .config import NotificationConfig

        config = NotificationConfig()
        notification = NotificationTemplates.daily_summary(business_name, metrics, config)
        return await self.send_notification(notification)

    async def send_weekly_report(
        self,
        business_name: str,
        weekly_data: dict
    ) -> bool:
        """Send weekly business intelligence report"""
        from .templates import NotificationTemplates
        from .config import NotificationConfig

        config = NotificationConfig()
        notification = NotificationTemplates.weekly_intelligence_report(business_name, weekly_data, config)
        return await self.send_notification(notification)

    async def send_technical_summary(
        self,
        summary_data: dict
    ) -> bool:
        """Send technical system summary"""
        from .templates import NotificationTemplates
        from .config import NotificationConfig

        config = NotificationConfig()
        notification = NotificationTemplates.technical_summary(summary_data, config)
        return await self.send_notification(notification)


    def get_registered_recipients(self):
        """Get all registered recipients"""
        return self.storage.get_all_recipients()

    async def test_connection(self) -> bool:
        """Test notification system connection"""
        if self.telegram_notifier:
            return await self.telegram_notifier.test_connection()
        return False

    async def cleanup(self):
        """Cleanup resources"""
        if self.telegram_notifier:
            await self.telegram_notifier.close()


_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Get or create global notification service instance"""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service


async def send_notification(
    title: str,
    message: str,
    role: NotificationRole,
    priority: NotificationPriority = NotificationPriority.MEDIUM,
    business_name: Optional[str] = None
) -> bool:
    """Quick function to send notification"""
    service = get_notification_service()
    notification = Notification.create(
        title=title,
        message=message,
        role=role,
        priority=priority,
        business_name=business_name
    )
    return await service.send_notification(notification)
