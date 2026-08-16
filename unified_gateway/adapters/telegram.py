"""
Telegram Platform Adapter

Handles Telegram-specific message format conversion and API communication.
Supports both webhook and polling modes.
"""

import logging
import json
import hashlib
import html
from typing import Dict, Any, Optional
import aiohttp
from datetime import datetime
import uuid
import socket
from urllib.parse import urlparse

from .base import PlatformAdapter
from ..models import (
    UnifiedMessage, DeliveryInfo, DeliveryStatus, Platform, MediaAttachment, MediaType
)
from ..config import PlatformConfig

logger = logging.getLogger(__name__)


class TelegramAdapter(PlatformAdapter):
    """Telegram platform adapter

    Supports both webhook and long-polling modes.
    Uses Telegram Bot API for message sending.
    """

    def __init__(self, config):
        super().__init__(config)
        self.platform_name = Platform.TELEGRAM.value
        self.bot_token = config.bot_token
        self.api_url = config.api_url or f"https://api.telegram.org/bot{self.bot_token}"
        self.webhook_secret = config.webhook_secret
        self.mode = getattr(config, 'mode', 'webhook')


        self.rate_limit_per_second = getattr(config, 'rate_limit_per_second', 20.0)
        self.rate_limit_burst = getattr(config, 'rate_limit_burst', 50)


        self._session: Optional[aiohttp.ClientSession] = None


        self._last_connectivity_check = None
        self._is_online = True


        self._last_network_notification_time = None
        self._network_notification_cooldown = 300
        self._last_network_status = "online"

    def _check_internet_connectivity(self) -> bool:
        """Check if there is internet connectivity

        Returns:
            True if internet is available, False otherwise
        """
        try:
            parsed = urlparse(self.api_url)
            host = parsed.hostname or 'api.telegram.org'
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)

            socket.setdefaulttimeout(5)
            socket.create_connection((host, port))
            logger.debug(f"Internet connectivity check passed for {host}")
            return True
        except (socket.timeout, socket.error) as e:
            logger.warning(f"Internet connectivity check failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during connectivity check: {e}")
            return False

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Close HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()

    def get_connectivity_status(self) -> Dict[str, Any]:
        """Get current connectivity status

        Returns:
            Dictionary with connectivity information
        """
        return {
            "is_online": self._is_online,
            "last_check": self._last_connectivity_check.isoformat() if self._last_connectivity_check else None
        }

    async def receive_message(self, raw_data: Dict[str, Any], bot_token: str = None) -> UnifiedMessage:
        """Convert Telegram webhook data to UnifiedMessage

        Args:
            raw_data: Telegram webhook update object
            bot_token: Optional bot token override (for multi-bot support)

        Returns:
            UnifiedMessage instance
        """

        message = raw_data.get('message', {})


        chat_id = str(message.get('chat', {}).get('id', ''))


        user_id = str(message.get('from', {}).get('id', ''))


        text = message.get('text', '')


        bot_id = bot_token or self.bot_token


        media_attachments = []
        if 'photo' in message:

            photos = message['photo']
            largest_photo = max(photos, key=lambda p: p.get('file_size', 0))
            media_attachments.append(MediaAttachment(
                type=MediaType.IMAGE,
                url=largest_photo.get('file_id', ''),
                caption=message.get('caption'),
                file_size=largest_photo.get('file_size')
            ))
        elif 'document' in message:
            doc = message['document']
            media_attachments.append(MediaAttachment(
                type=MediaType.DOCUMENT,
                url=doc.get('file_id', ''),
                mime_type=doc.get('mime_type'),
                caption=message.get('caption'),
                file_size=doc.get('file_size')
            ))
        elif 'video' in message:
            video = message['video']
            media_attachments.append(MediaAttachment(
                type=MediaType.VIDEO,
                url=video.get('file_id', ''),
                mime_type=video.get('mime_type'),
                caption=message.get('caption'),
                file_size=video.get('file_size')
            ))
        elif 'audio' in message:
            audio = message['audio']
            media_attachments.append(MediaAttachment(
                type=MediaType.AUDIO,
                url=audio.get('file_id', ''),
                mime_type=audio.get('mime_type'),
                caption=message.get('caption'),
                file_size=audio.get('file_size')
            ))


        unified_msg = UnifiedMessage(
            id=str(uuid.uuid4()),
            platform=Platform.TELEGRAM,
            user_id=user_id,
            business="yo_bakery",
            content=text,
            media=media_attachments if media_attachments else None,
            metadata={
                'update_id': raw_data.get('update_id'),
                'message_id': message.get('message_id'),
                'chat_id': message.get('chat', {}).get('id'),
                'chat_type': message.get('chat', {}).get('type'),
                'bot_id': bot_id,
                'raw_message': message
            }
        )

        return unified_msg

    async def send_message(self, message: UnifiedMessage) -> DeliveryInfo:
        """Send message via Telegram Bot API

        Args:
            message: UnifiedMessage to send

        Returns:
            DeliveryInfo with status
        """
        session = await self._get_session()
        delivery_info = self.create_delivery_info(message)

        url = f"{self.api_url}/sendMessage"

        logger.debug(f"API URL: {url}")


        formatted_text = self.format_message(message.content)


        chat_id = message.metadata.get('chat_id') if message.metadata else None
        if not chat_id:
            chat_id = message.user_id


        try:
            chat_id = int(chat_id)
        except (ValueError, TypeError):

            pass

        logger.debug(f"Original content: {message.content}")
        logger.debug(f"Formatted text: {formatted_text}")
        logger.debug(f"Sending message to chat_id: {chat_id} (type: {type(chat_id).__name__}), user_id: {message.user_id}")

        payload = {
            "chat_id": chat_id,
            "text": formatted_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        try:
            async with session.post(url, json=payload) as response:
                response_data = await response.json()

                if response.status == 200 and response_data.get('ok'):

                    delivery_info.status = DeliveryStatus.SENT
                    delivery_info.sent_at = datetime.now()
                    delivery_info.updated_at = datetime.now()


                    result = response_data.get('result', {})
                    if 'message_id' in result:
                        delivery_info.metadata = {
                            'telegram_message_id': result['message_id']
                        }

                    logger.info(f"Message sent to Telegram user {message.user_id}")
                    self._is_online = True
                    self._last_connectivity_check = datetime.now()
                else:

                    error_msg = response_data.get('description', 'Unknown error')
                    delivery_info.status = DeliveryStatus.FAILED
                    delivery_info.last_error = error_msg
                    delivery_info.updated_at = datetime.now()

                    logger.error(f"Failed to send message to Telegram: {error_msg}, response: {response_data}")

        except aiohttp.ClientConnectorError as e:

            error_msg = f"Network connection error: {str(e)}"
            delivery_info.status = DeliveryStatus.FAILED
            delivery_info.last_error = error_msg
            delivery_info.updated_at = datetime.now()

            self._is_online = False
            self._last_connectivity_check = datetime.now()
            logger.error(f"Network connection error when sending to Telegram: {e}")
            logger.error("Please check your internet connection and try again.")


            await self._send_network_notification("offline", str(e))

        except aiohttp.ClientTimeout as e:

            error_msg = f"Request timeout: {str(e)}"
            delivery_info.status = DeliveryStatus.FAILED
            delivery_info.last_error = error_msg
            delivery_info.updated_at = datetime.now()

            logger.error(f"Request timeout when sending to Telegram: {e}")
            logger.error("The request timed out. Check your network connection.")


            await self._send_error_notification("TimeoutError", str(e), "send_message")

        except Exception as e:
            delivery_info.status = DeliveryStatus.FAILED
            delivery_info.last_error = str(e)
            delivery_info.updated_at = datetime.now()

            logger.error(f"Error sending message to Telegram: {e}")


            await self._send_error_notification("TelegramSendError", str(e), "send_message")

        return delivery_info

    async def setup_webhook(self, webhook_url: str) -> bool:
        """Configure Telegram webhook

        Args:
            webhook_url: URL to receive webhooks

        Returns:
            True if successful
        """
        session = await self._get_session()
        url = f"{self.api_url}/setWebhook"

        payload = {
            "url": webhook_url
        }

        if self.webhook_secret:
            payload["secret_token"] = self.webhook_secret

        try:
            async with session.post(url, json=payload) as response:
                response_data = await response.json()

                if response_data.get('ok'):
                    logger.info(f"Telegram webhook set to {webhook_url}")
                    self._is_online = True
                    return True
                else:
                    error_msg = response_data.get('description', 'Unknown error')
                    logger.error(f"Failed to set Telegram webhook: {error_msg}")
                    return False

        except aiohttp.ClientConnectorError as e:

            self._is_online = False
            logger.error(f"Network connection error when setting Telegram webhook: {e}")
            logger.error("Please check your internet connection and try again.")
            return False

        except aiohttp.ClientTimeout as e:

            logger.error(f"Request timeout when setting Telegram webhook: {e}")
            logger.error("The request timed out. Check your network connection.")
            return False

        except Exception as e:
            logger.error(f"Error setting Telegram webhook: {e}")
            return False

    async def verify_webhook(self, headers: Dict, body: Any) -> bool:
        """Verify Telegram webhook authenticity

        Args:
            headers: HTTP headers
            body: Request body

        Returns:
            True if webhook is authentic
        """
        logger.debug(f"Verifying Telegram webhook")
        logger.debug(f"  Configured secret: {self.webhook_secret}")
        logger.debug(f"  Received secret token: {headers.get('X-Telegram-Bot-Api-Secret-Token')}")


        if self.webhook_secret:
            secret_token = headers.get('X-Telegram-Bot-Api-Secret-Token')
            if secret_token and secret_token != self.webhook_secret:
                logger.warning(f"✗ Telegram webhook secret token mismatch")
                logger.warning(f"  Expected: {self.webhook_secret}")
                logger.warning(f"  Received: {secret_token}")
                return False
            elif not secret_token:
                logger.warning(f"✗ Telegram webhook secret token missing")
                logger.warning(f"  Expected: {self.webhook_secret}")
                logger.warning(f"  Note: Configure secret token in Telegram webhook setup")


        logger.debug("✓ Telegram webhook verified successfully")


        return True

    def format_message(self, text: str) -> str:
        """Format text for Telegram (HTML)

        Converts plain text to Telegram HTML format.

        Args:
            text: Unified text content

        Returns:
            HTML-formatted text for Telegram
        """
        import re
        try:


            text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)


            text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)


            text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)


            text = re.sub(r'```(.+?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)


            tags = []
            def save_tag(match):
                tags.append(match.group(0))
                return f"\x00{len(tags)-1}\x00"
            text = re.sub(r'<(?:b|i|code|pre)>|</(?:b|i|code|pre)>', save_tag, text)


            text = html.escape(text)


            text = text.replace('&lt;', '<').replace('&gt;', '>')
            for i, tag in enumerate(tags):
                text = text.replace(f"\x00{i}\x00", tag)


            text = self._validate_and_fix_html_tags(text)

            return text
        except Exception as e:
            logger.error(f"Error formatting message: {e}, falling back to plain text")

            return html.escape(text)

    def _validate_and_fix_html_tags(self, text: str) -> str:
        """Validate and fix mismatched HTML tags

        Args:
            text: Text with HTML tags

        Returns:
            Text with validated HTML tags
        """
        import re
        try:

            opening_tags = re.findall(r'<(b|i|code|pre)>', text)
            closing_tags = re.findall(r'</(b|i|code|pre)>', text)

            tag_counts = {}
            for tag in opening_tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            for tag in closing_tags:
                tag_counts[tag] = tag_counts.get(tag, 0) - 1


            for tag, count in tag_counts.items():
                if count < 0:

                    text = re.sub(f'</{tag}>', '', text, abs(count))


            for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
                if count > 0:
                    text += f'</{tag}>' * count

            return text
        except Exception as e:
            logger.error(f"Error validating HTML tags: {e}, returning original text")
            return text

    async def get_file_url(self, file_id: str) -> Optional[str]:
        """Get file download URL from Telegram

        Args:
            file_id: Telegram file ID

        Returns:
            File URL or None if not found
        """
        session = await self._get_session()


        url = f"{self.api_url}/getFile"
        payload = {"file_id": file_id}

        try:
            async with session.post(url, json=payload) as response:
                response_data = await response.json()

                if response_data.get('ok'):
                    result = response_data.get('result', {})
                    file_path = result.get('file_path')
                    if file_path:
                        return f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"

        except aiohttp.ClientConnectorError as e:
            self._is_online = False
            logger.error(f"Network connection error when getting file URL: {e}")
            logger.error("Please check your internet connection and try again.")

        except aiohttp.ClientTimeout as e:
            logger.error(f"Request timeout when getting file URL: {e}")
            logger.error("The request timed out. Check your network connection.")

        except Exception as e:
            logger.error(f"Error getting file URL: {e}")

        return None

    async def _send_error_notification(self, error_type: str, error_message: str, context: str):
        """Send error notification"""
        try:
            from notification_system.service import get_notification_service
            service = get_notification_service()
            await service.send_error_notification(error_type, error_message, context)
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Failed to send error notification: {e}")

    async def _send_network_notification(self, status: str, details: str):
        """Send network status notification with deduplication"""
        from datetime import datetime
        now = datetime.now()


        if self._last_network_notification_time:
            time_since_last = (now - self._last_network_notification_time).total_seconds()
            if time_since_last < self._network_notification_cooldown:
                logger.debug(f"Network notification suppressed (cooldown: {self._network_notification_cooldown - time_since_last:.0f}s remaining)")
                return


        if (status == "offline" and self._last_network_status == "online") or \
           (status == "online" and self._last_network_status == "offline"):
            self._last_network_notification_time = now
            self._last_network_status = status

            try:
                from notification_system.service import get_notification_service
                service = get_notification_service()
                await service.send_network_status_change(status, details)
            except ImportError:
                pass
            except Exception as e:
                logger.warning(f"Failed to send network notification: {e}")
