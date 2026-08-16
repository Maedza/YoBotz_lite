"""
Dedicated Telegram notification sender
"""
import os
import aiohttp
import asyncio
from typing import List, Optional
import logging

from .chat_id_store import ChatIDStorage, RecipientType
from .models import Notification, NotificationRole, NotificationPriority

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Dedicated Telegram notification sender"""

    def __init__(self, bot_token: str, storage=None):
        if not bot_token:
            raise ValueError("Telegram bot token is required")

        self.bot_token = bot_token

        self.storage = storage or ChatIDStorage()
        self._session: Optional[aiohttp.ClientSession] = None
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    async def ensure_session(self):
        """Ensure HTTP session exists"""
        if not self._session or self._session.closed:
            # Don't use timeout in session constructor - causes issues in thread-based event loops
            self._session = aiohttp.ClientSession()

    async def close(self):
        """Close HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()

    def _map_role_to_recipient_type(self, role: NotificationRole) -> RecipientType:
        """Map NotificationRole to RecipientType"""
        if role == NotificationRole.BUSINESS_OWNER:
            return RecipientType.BUSINESS_OWNER
        elif role == NotificationRole.DEVELOPER:
            return RecipientType.DEVELOPER
        elif role == NotificationRole.SYSTEM_ADMIN:
            return RecipientType.SYSTEM_ADMIN
        else:
            return RecipientType.DEVELOPER

    async def send_notification(self, notification: Notification) -> bool:
        """Send notification to appropriate recipients"""
        await self.ensure_session()


        recipient_type = self._map_role_to_recipient_type(notification.role)


        chat_ids = self.storage.get_chat_ids(
            recipient_type=recipient_type,
            business_name=notification.business_name,
        )

        if not chat_ids:
            logger.warning(
                f"No recipients found for {notification.role} - {notification.business_name}"
            )
            return False


        message = self._format_message(notification)


        tasks = []
        for chat_id in chat_ids:
            task = self._send_to_telegram(
                chat_id, message, notification.priority)
            tasks.append(task)


        results = await asyncio.gather(*tasks, return_exceptions=True)


        success_count = 0
        for i, result in enumerate(results):
            chat_id = chat_ids[i]
            if isinstance(result, Exception):
                logger.error(f"Failed to send to {chat_id}: {result}")
            elif result:
                success_count += 1

        if success_count > 0:
            logger.info(
                f"Notification sent to {success_count}/{len(chat_ids)} recipients: {notification.title}"
            )
            return True
        else:
            logger.error(
                f"Failed to send notification to any recipient: {notification.title}"
            )
            return False

    def _format_message(self, notification: Notification) -> str:
        """Format notification message for Telegram"""

        return notification.format_for_telegram()

    async def _send_to_telegram(
        self, chat_id: str, message: str, priority: NotificationPriority
    ) -> bool:
        """Send message to Telegram with retry and rate-limiting"""
        url = f"{self.base_url}/sendMessage"


        disable_notification = priority == NotificationPriority.LOW

        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_notification": disable_notification,
            "disable_web_page_preview": True,
        }

        for attempt in range(3):
            try:
                async with self._session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Telegram API error {response.status} for chat {chat_id}: {error_text}"
                        )
            except asyncio.TimeoutError:
                logger.error(
                    f"Timeout sending to chat {chat_id}, attempt {attempt + 1}"
                )
            except Exception as e:
                logger.error(
                    f"Telegram connection error for chat {chat_id}, attempt {attempt + 1}: {e}"
                )

            await asyncio.sleep(2**attempt)

        logger.error(
            f"Failed to send message to chat {chat_id} after 3 attempts")
        return False

    async def test_connection(self) -> bool:
        """Test Telegram bot connection"""
        await self.ensure_session()

        url = f"{self.base_url}/getMe"

        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("ok"):
                        bot_name = data["result"]["username"]
                        logger.info(f"Telegram bot connected: @{bot_name}")
                        return True
                return False
        except Exception as e:
            logger.error(f"Failed to connect to Telegram: {e}")
            return False
