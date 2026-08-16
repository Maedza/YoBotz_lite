"""
Unified Messaging Gateway Configuration

Loads and manages configuration for the unified gateway.
"""

import os
import re
from typing import Dict, Any, Optional
from dataclasses import dataclass
import yaml


def expand_env_vars(obj):
    """Expand environment variables in strings"""
    if isinstance(obj, str):

        pattern = r'\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)'
        def replace_match(match):
            var_name = match.group(1) or match.group(2)
            return os.getenv(var_name, match.group(0))
        return re.sub(pattern, replace_match, obj)
    elif isinstance(obj, dict):
        return {k: expand_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [expand_env_vars(item) for item in obj]
    else:
        return obj


@dataclass
class PlatformConfig:
    """Configuration for a platform adapter"""
    enabled: bool
    bot_token: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    api_url: Optional[str] = None
    rate_limit_per_second: float = 20.0
    rate_limit_burst: int = 50


@dataclass
class GatewayConfig:
    """Unified gateway configuration"""
    port: int = 8000
    log_level: str = "INFO"
    default_business: str = "yo_bakery"


    redis_url: str = "redis://localhost:6379/0"


    delivery_retry_max_attempts: int = 3
    delivery_retry_base_delay: float = 2.0
    delivery_retry_max_delay: float = 60.0


    telegram: PlatformConfig = None

    @classmethod
    def from_env(cls) -> 'GatewayConfig':
        """Load configuration from environment variables"""
        config = cls()


        config.port = int(os.getenv("PORT", "8000"))
        config.log_level = os.getenv("LOG_LEVEL", "INFO")
        config.default_business = os.getenv("DEFAULT_BUSINESS", "yo_bakery")


        config.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")


        config.delivery_retry_max_attempts = int(
            os.getenv("DELIVERY_RETRY_MAX_ATTEMPTS", "3")
        )
        config.delivery_retry_base_delay = float(
            os.getenv("DELIVERY_RETRY_BASE_DELAY", "2.0")
        )
        config.delivery_retry_max_delay = float(
            os.getenv("DELIVERY_RETRY_MAX_DELAY", "60.0")
        )


        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        telegram_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
        config.telegram = PlatformConfig(
            enabled=bool(telegram_token),
            bot_token=telegram_token,
            webhook_secret=telegram_secret if telegram_secret else None,
            api_url=f"https://api.telegram.org/bot{telegram_token or ''}"
        )

        return config

    @classmethod
    def from_yaml(cls, path: str = "unified_gateway_config.yaml") -> 'GatewayConfig':
        """Load configuration from YAML file"""
        config = cls()

        try:
            with open(path, 'r') as f:
                data = yaml.safe_load(f)


            data = expand_env_vars(data)


            if "server" in data:
                server_config = data["server"]
                config.port = server_config.get("port", 8000)
                config.log_level = server_config.get("log_level", "INFO")
                config.default_business = server_config.get("default_business", "yo_bakery")


            if "redis" in data:
                config.redis_url = data["redis"].get("url", "redis://localhost:6379/0")


            if "delivery" in data:
                delivery_config = data["delivery"]
                config.delivery_retry_max_attempts = delivery_config.get("max_attempts", 3)
                config.delivery_retry_base_delay = delivery_config.get("base_delay", 2.0)
                config.delivery_retry_max_delay = delivery_config.get("max_delay", 60.0)


            if "platforms" in data:
                platforms = data["platforms"]


                if "telegram" in platforms:
                    telegram_config = platforms["telegram"]
                    config.telegram = PlatformConfig(
                        enabled=telegram_config.get("enabled", False),
                        bot_token=telegram_config.get("bot_token"),
                        webhook_url=telegram_config.get("webhook_url"),
                        webhook_secret=telegram_config.get("webhook_secret"),
                        api_url=telegram_config.get("api_url"),
                        rate_limit_per_second=telegram_config.get("rate_limit_per_second", 20.0),
                        rate_limit_burst=telegram_config.get("rate_limit_burst", 50)
                    )

        except FileNotFoundError:

            return cls.from_env()
        except Exception as e:
            print(f"Error loading config from YAML: {e}")
            return cls.from_env()

        return config


def load_config(config_path: Optional[str] = None) -> GatewayConfig:
    """Load configuration from YAML or environment variables"""
    if config_path:
        return GatewayConfig.from_yaml(config_path)
    else:

        try:
            return GatewayConfig.from_yaml("unified_gateway_config.yaml")
        except:
            return GatewayConfig.from_env()
