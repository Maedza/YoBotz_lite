"""
BusinessRegistry: Auto-discovers businesses and manages vault lifecycle.

Thread-safe singleton. On startup it scans the businesses/ directory
and creates a BusinessVault for each one. Supports graceful hot-reload.
"""

import os
import json
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any

from core.business_loader import list_businesses
from core.business_vault import BusinessVault

logger = logging.getLogger(__name__)

_REDIS_URL_ENV = "REDIS_URL"
_REGISTRY_KEY = "biz:_registry"


class BusinessRegistry:
    """
    Central registry for all business vaults.

    Handles:
    - Auto-discovery at startup
    - Lazy vault creation (one per business)
    - Graceful hot-reload with lock + atomic swap
    - Admin onboarding (register / deregister)
    """

    _instance: Optional["BusinessRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls, redis_url: Optional[str] = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init(redis_url)
        return cls._instance

    def _init(self, redis_url: Optional[str] = None):
        self._vaults: Dict[str, BusinessVault] = {}
        self._vault_lock = threading.RLock()
        self._redis_url = redis_url or os.getenv(_REDIS_URL_ENV)
        self._initialized = False


    def discover_all(self) -> List[str]:
        """
        Scan businesses/ directory, create vaults for each found business,
        and sync the registry list to Redis (if available).

        Safe to call multiple times — subsequent calls only add new businesses.
        """
        business_names = list_businesses()

        with self._vault_lock:
            added = []
            for name in business_names:
                if name not in self._vaults:
                    vault = BusinessVault(name, self._redis_url)
                    self._vaults[name] = vault
                    added.append(name)
                    logger.info(f"BusinessRegistry: discovered '{name}'")

            if added:
                logger.info(f"BusinessRegistry: discovered {len(added)} new businesses: {added}")

            self._initialized = True
            self._sync_registry_list(business_names)

        return business_names

    def _sync_registry_list(self, names: List[str]):
        """Write the full business list to Redis."""
        if not self._redis_url:
            return
        try:
            import redis
            client = redis.from_url(self._redis_url)
            client.set(_REGISTRY_KEY, json.dumps(names))
            logger.debug(f"BusinessRegistry: synced {len(names)} businesses to Redis")
        except Exception as e:
            logger.warning(f"BusinessRegistry: failed to sync list to Redis: {e}")


    def get_vault(self, business_name: str) -> Optional[BusinessVault]:
        """Get vault for a business, creating it lazily if discovered."""
        with self._vault_lock:
            if business_name not in self._vaults:

                from core.business_loader import list_businesses
                if business_name not in list_businesses():
                    logger.warning(
                        f"BusinessRegistry: no such business '{business_name}'"
                    )
                    return None
                self._vaults[business_name] = BusinessVault(
                    business_name, self._redis_url
                )
                self._sync_registry_list(list(self._vaults.keys()))

            return self._vaults[business_name]

    def get_vault_safe(self, business_name: str) -> BusinessVault:
        """Like get_vault but always returns a vault (creates empty one)."""
        vault = self.get_vault(business_name)
        if vault is None:
            with self._vault_lock:
                vault = BusinessVault(business_name, self._redis_url)
                self._vaults[business_name] = vault
        return vault


    def register_business(
        self,
        business_name: str,
        secrets: Dict[str, str],
        webhook_url: Optional[str] = None,
        config_blobs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Onboard a new business via API.

        Creates the vault, persists secrets + config blobs to Redis,
        registers the business engine, and optionally sets up the
        Telegram webhook.

        ``config_blobs`` keys: ``config``, ``responses``, ``products``,
        ``services`` — each a parsed dict. Stored in Redis so the
        business persists without relying on filesystem dirs.
        """
        if not business_name or not business_name.replace("_", "").isalnum():
            raise ValueError("Invalid business name (alphanumeric + underscore only)")

        vault = self.get_vault_safe(business_name)


        for key, value in secrets.items():
            vault.set_secret(key, value)


        blobs_written = 0
        if config_blobs:
            for blob_name, blob_data in config_blobs.items():
                if blob_data and isinstance(blob_data, (dict, list)):
                    vault.set_config_blob(blob_name, blob_data)
                    blobs_written += 1
                    logger.info(
                        f"BusinessRegistry: persisted config blob "
                        f"'{blob_name}' for '{business_name}'"
                    )


        bot_token = vault.bot_token
        if bot_token and webhook_url:
            self._set_webhook(bot_token, webhook_url, business_name)

        logger.info(f"BusinessRegistry: registered '{business_name}'")
        return {
            "business_name": business_name,
            "secrets_written": len(secrets),
            "config_blobs_written": blobs_written,
        }

    def deregister_business(self, business_name: str) -> bool:
        """Remove a business from the registry."""
        with self._vault_lock:
            if business_name in self._vaults:
                del self._vaults[business_name]
                logger.info(f"BusinessRegistry: deregistered '{business_name}'")

        if self._redis_url:
            try:
                import redis
                client = redis.from_url(self._redis_url)
                pattern = f"biz:{business_name}:*"
                for key in client.keys(pattern):
                    client.delete(key)
                remaining = [n for n in self._vaults.keys()]
                client.set(_REGISTRY_KEY, json.dumps(remaining))
            except Exception as e:
                logger.warning(f"BusinessRegistry: Redis cleanup failed: {e}")

        return True

    def _set_webhook(self, bot_token: str, webhook_url: str, business_name: str):
        """Register Telegram webhook for a newly onboarded business."""
        try:
            import requests
            secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
            payload = {"url": webhook_url, "drop_pending_updates": True}
            if secret:
                payload["secret_token"] = secret
            resp = requests.post(
                f"https://api.telegram.org/bot{bot_token}/setWebhook",
                json=payload,
                timeout=15
            )
            resp.raise_for_status()
            logger.info(
                f"BusinessRegistry: webhook set for '{business_name}' at {webhook_url}"
            )
        except Exception as e:
            logger.warning(
                f"BusinessRegistry: failed to set webhook for '{business_name}': {e}"
            )


    def reload(self, business_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Graceful hot-reload.

        If business_name is None, reloads all.
        Uses lock + atomic dict swap so in-flight messages see no disruption.
        """
        with self._vault_lock:
            result = {"reloaded": []}
            targets = (
                [business_name] if business_name
                else list(self._vaults.keys())
            )

            for name in targets:
                if name in self._vaults:
                    self._vaults[name].reload()
                    result["reloaded"].append(name)

            logger.info(f"BusinessRegistry: hot-reloaded {result['reloaded']}")
            return result


    def list_businesses(self) -> List[str]:
        """Return all registered business names."""
        with self._vault_lock:
            return list(self._vaults.keys())

    def is_initialized(self) -> bool:
        return self._initialized

    @classmethod
    def reset(cls):
        """Reset singleton (for testing only)."""
        with cls._lock:
            cls._instance = None
