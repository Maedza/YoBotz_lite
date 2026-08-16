"""
Business Resolver - Bot ID to Business Mapping

Resolves business context from bot ID.
Loads from BusinessVault (Redis in prod, file-based in dev).
"""
import logging
from typing import Optional

from core.business_registry import BusinessRegistry

logger = logging.getLogger(__name__)


class BusinessResolver:
    """Resolves business name from bot ID via BusinessVault."""

    _instance = None
    _token_to_business: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_mappings()
        return cls._instance

    def _load_mappings(self):
        """Build bot_token -> business_name map from all vaults."""
        self._token_to_business = {}
        try:
            registry = BusinessRegistry()
            for biz_name in registry.list_businesses():
                vault = registry.get_vault(biz_name)
                if vault:
                    token = vault.bot_token
                    if token:
                        self._token_to_business[token] = biz_name
                        logger.debug(f"BusinessResolver: mapped token to '{biz_name}'")
        except Exception as e:
            logger.warning(f"BusinessResolver: failed to load from registry: {e}")

            import os
            prefix = "BOT_IDS_"
            for key, value in os.environ.items():
                if key.startswith(prefix):
                    biz_name = key[len(prefix):].lower()
                    for token in value.strip().split(','):
                        token = token.strip()
                        if token:
                            self._token_to_business[token] = biz_name

        logger.info(f"BusinessResolver: loaded {len(self._token_to_business)} token mappings")

    def resolve_business(self, bot_id: Optional[str] = None) -> Optional[str]:
        """Resolve business name from bot token."""
        if not bot_id:
            return None
        return self._token_to_business.get(bot_id)

    def get_business_bot_id(self, business_name: str) -> Optional[str]:
        """Reverse lookup: get bot token for a business."""
        try:
            registry = BusinessRegistry()
            vault = registry.get_vault(business_name)
            if vault:
                return vault.bot_token
        except Exception as e:
            logger.warning(f"BusinessResolver: failed to get bot_id for '{business_name}': {e}")


        import os
        env_key = f"BOT_IDS_{business_name.upper()}"
        return os.getenv(env_key, "").split(',')[0].strip() or None

    def reload_mappings(self):
        """Reload mappings from vaults."""
        self._load_mappings()
        logger.info("BusinessResolver: mappings reloaded")
