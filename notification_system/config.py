"""
Load configuration from YAML file with role support
"""
import os
import yaml
from pathlib import Path
from typing import Dict, Any, List
import logging
from dotenv import load_dotenv


load_dotenv()

logger = logging.getLogger(__name__)

class NotificationConfig:
    """Configuration loader with role-based routing"""

    def __init__(self):
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load from YAML or use defaults"""
        config_path = Path("data/configs/notification_config.yaml")

        if not config_path.exists():
            logger.warning("No notification_config.yaml found at data/configs/, using defaults")
            return self._get_default_config()

        try:
            with open(config_path, 'r') as f:
                content = f.read()

                for key, value in os.environ.items():
                    content = content.replace(f"${{{key}}}", value)
                config = yaml.safe_load(content)

            logger.info("✅ Loaded notification configuration")
            return config

        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """Default configuration"""
        return {
            'enabled': True,
            'telegram': {
                'enabled': True,
                'chat_id': '8333321929',
                'bot_token': os.getenv("NOTIFICATION_BOT_TOKEN", "")
            },
            'log_to_console': True,
            'log_monitor': {
                'enabled': True,
                'files': ['unified_gateway.log']
            }
        }

    def get_telegram_chat_id(self) -> str:
        """Get Telegram chat ID (default)"""
        return self.config.get('telegram', {}).get('chat_id', '8333321929')

    def get_telegram_bot_token(self) -> str:
        """Get Telegram bot token"""

        token = self.config.get('telegram', {}).get('settings', {}).get('bot_token', '')


        if token.startswith('${') and token.endswith('}'):
            env_var = token[2:-1]
            token = os.getenv(env_var, "")


        if not token:
            token = self.config.get('telegram', {}).get('bot_token', '')  # legacy location


        if not token:
            token = os.getenv("NOTIFICATION_BOT_TOKEN", "")

        return token

    def get_chat_id_for_role(self, role: str) -> str:
        """Get Telegram chat ID for specific role"""

        chat_ids = self.config.get('telegram', {}).get('settings', {}).get('chat_ids', {})


        if not chat_ids:
            chat_ids = self.config.get('telegram', {}).get('chat_ids', {})


        if role in chat_ids:
            logger.debug(f"Found chat ID for role '{role}': {chat_ids[role]}")
            return chat_ids[role]


        default = self.config.get('telegram', {}).get('chat_id', '8333321929')
        logger.debug(f"No chat ID for role '{role}', using default: {default}")
        return default

    def get_business_display_name(self, business_slug: str) -> str:
        """Get display name for business"""

        display_map = self.config.get('business', {}).get('display_name_map', {})
        if business_slug in display_map:
            return display_map[business_slug]


        try:
            from smart_engine.core.utils.business_utils import get_business_display_name
            return get_business_display_name(business_slug)
        except ImportError:
            logger.debug(f"Could not import smart_engine utils for {business_slug}")


        return business_slug.replace('_', ' ').title()

    def get_business_timezone(self, business_slug: str) -> str:
        """Get timezone for a specific business"""

        business_config = self.config.get('business_settings', {}).get(business_slug, {})
        business_tz = business_config.get('timezone')

        if business_tz:
            logger.debug(f"Using business-specific timezone for {business_slug}: {business_tz}")
            return business_tz


        global_tz = os.getenv('TIMEZONE')
        if global_tz:
            logger.debug(f"Using global timezone for {business_slug}: {global_tz}")
            return global_tz


        logger.debug(f"No timezone found for {business_slug}, using UTC")
        return 'UTC'

    def get_daily_summary_time(self) -> str:
        """Get time for daily summary"""
        return self.config.get('schedule', {}).get('business_summary', '21:00')

    def should_send_to_role(self, role: str, priority_value: str) -> bool:
        """Check if a role should receive notifications of given priority"""
        role_config = self.config.get('roles', {}).get(role, {})
        allowed_priorities = role_config.get('priority_filter', ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'])

        return priority_value in allowed_priorities

    def is_enabled(self) -> bool:
        """Check if notifications are enabled"""
        return self.config.get('enabled', True)

    def is_telegram_enabled(self) -> bool:
        """Check if Telegram is enabled"""
        return self.config.get('telegram', {}).get('enabled', True)

    def should_monitor_logs(self) -> bool:
        """Check if log monitoring is enabled"""
        return self.config.get('log_monitor', {}).get('enabled', True)

    def get_log_files(self) -> List[str]:
        """Get log files to monitor"""
        return self.config.get('log_monitor', {}).get('files', ['unified_gateway.log'])
