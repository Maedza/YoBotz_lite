"""
TokenRegistry: Manages bot tokens for different businesses via BusinessVault.
"""
import logging
from typing import Dict, Optional

from core.business_registry import BusinessRegistry

logger = logging.getLogger(__name__)


class TokenRegistry:
    """Registry for notification bot tokens per business, backed by BusinessVault."""

    def __init__(self):
        self._cache: Dict[str, str] = {}
        self._registry: Optional[BusinessRegistry] = None

    @property
    def registry(self) -> BusinessRegistry:
        if self._registry is None:
            self._registry = BusinessRegistry()
        return self._registry

    def get_token(self, business_name: Optional[str]) -> str:
        """
        Get notification bot token for a business.
        Returns empty string if not found.
        """
        if not business_name:
            return ""

        if business_name in self._cache:
            return self._cache[business_name]

        vault = self.registry.get_vault(business_name)
        token = vault.notification_bot_token if vault else None

        if token:
            self._cache[business_name] = token
            logger.info(f"TokenRegistry: loaded token for '{business_name}'")
        else:

            import os
            fallback = os.getenv(f"NOTIFICATION_BOT_TOKEN_{business_name.upper()}", "")
            if fallback:
                logger.info(f"TokenRegistry: using legacy env fallback for '{business_name}'")
            self._cache[business_name] = fallback

        return self._cache[business_name]

    def clear_cache(self) -> None:
        self._cache.clear()
        logger.info("TokenRegistry: cache cleared")

    def preload_tokens(self, business_names: list) -> None:
        for name in business_names:
            self.get_token(name)
