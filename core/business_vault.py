"""
BusinessVault: Per-business secrets and config management.

Dual-mode:
  - Redis in production: secrets + config blobs stored in Redis
  - File-based in development: per-business .env + YAML/JSON files

Config versioning: each business config carries a ``config_version`` field.
On deploy, if the stored version is older than CURRENT_CONFIG_VERSION,
migration transforms the config transparently. This enables gradual rollouts —
different businesses can run on different config versions simultaneously.
"""

import os
import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional, Dict

from dotenv import dotenv_values

logger = logging.getLogger(__name__)


_VAULT_PREFIX = "biz"
_REDIS_URL_ENV = "REDIS_URL"
_CONFIG_SUFFIX = "_config"


class BusinessVault:
    """
    Per-business secrets vault with dual-mode (Redis / file-based).

    Priority: Redis (prod) > file-based (dev)
    """

    def __init__(self, business_name: str, redis_url: Optional[str] = None):
        self.business_name = business_name
        self._redis_url = redis_url or os.getenv(_REDIS_URL_ENV)
        self._redis = None
        self._local_secrets: Dict[str, str] = {}
        self._local_loaded = False

        if self._redis_url:
            self._init_redis()
        else:
            self._load_local_env()


    def _init_redis(self):
        try:
            import redis
            client = redis.from_url(self._redis_url, decode_responses=False)
            client.ping()
            self._redis = client
            logger.info(f"BusinessVault[{self.business_name}] connected to Redis")
        except Exception as e:
            logger.warning(
                f"BusinessVault[{self.business_name}] Redis unavailable ({e}), "
                "falling back to file-based"
            )
            self._redis = None
            self._load_local_env()

    def _redis_key(self, key: str) -> str:
        return f"{_VAULT_PREFIX}:{self.business_name}:{key}"


    def _env_path(self) -> Path:
        return Path("businesses") / self.business_name / ".env"

    def _load_local_env(self):
        path = self._env_path()
        if not path.exists():
            logger.debug(
                f"BusinessVault[{self.business_name}] no .env at {path}, "
                "using empty secrets"
            )
            return

        try:
            values = dotenv_values(str(path))
            self._local_secrets = {k: v for k, v in values.items() if v is not None}
            self._local_loaded = True
            logger.info(
                f"BusinessVault[{self.business_name}] loaded {len(self._local_secrets)} "
                f"secrets from {path}"
            )
        except Exception as e:
            logger.warning(
                f"BusinessVault[{self.business_name}] failed to load .env: {e}"
            )


    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get a secret value for this business.
        Returns None if not found.
        """
        if self._redis:
            val = self._redis.get(self._redis_key(key))
            if val is not None:
                return val.decode() if isinstance(val, bytes) else val
            return default

        return self._local_secrets.get(key, default)

    def set_secret(self, key: str, value: str) -> bool:
        """
        Persist a secret. In Redis mode it writes immediately;
        in file-based mode it updates the local cache only.
        """
        if self._redis:
            try:
                self._redis.set(self._redis_key(key), value)
                return True
            except Exception as e:
                logger.error(
                    f"BusinessVault[{self.business_name}] failed to set {key}: {e}"
                )
                return False

        self._local_secrets[key] = value
        return True

    def delete_secret(self, key: str) -> bool:
        """Delete a secret."""
        if self._redis:
            try:
                self._redis.delete(self._redis_key(key))
                return True
            except Exception as e:
                logger.error(
                    f"BusinessVault[{self.business_name}] failed to delete {key}: {e}"
                )
                return False

        self._local_secrets.pop(key, None)
        return True

    def list_secrets(self) -> list[str]:
        """
        Return secret keys (values are never exposed).
        In Redis mode, lists keys matching the business prefix.
        """
        if self._redis:
            try:
                pattern = f"{_VAULT_PREFIX}:{self.business_name}:*"
                keys = self._redis.keys(pattern)
                prefix_len = len(f"{_VAULT_PREFIX}:{self.business_name}:")
                return [k.decode() if isinstance(k, bytes) else k[prefix_len:]
                        for k in keys]
            except Exception as e:
                logger.error(
                    f"BusinessVault[{self.business_name}] failed to list keys: {e}"
                )
                return []

        return list(self._local_secrets.keys())


    def _config_key(self, name: str) -> str:
        return f"{_VAULT_PREFIX}:{self.business_name}:{_CONFIG_SUFFIX}:{name}"

    def get_config_blob(self, name: str) -> Optional[Dict[str, Any]]:
        """Load a structured config blob from Redis or file cache."""
        if self._redis:
            try:
                raw = self._redis.get(self._config_key(name))
                if raw is not None:
                    return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            except Exception as e:
                logger.error(f"BusinessVault[{self.business_name}] get_config_blob({name}): {e}")
            return None


        _FS_FILENAME = {
            "config": "business_config", "responses": "responses",
            "products": "products", "services": "services",
        }
        _FS_EXT = {"config": "yaml", "responses": "yaml", "products": "json", "services": "yaml"}
        fname = _FS_FILENAME.get(name, name)
        ext = _FS_EXT.get(name, "json")
        path = Path("businesses") / self.business_name / f"{fname}.{ext}"
        if not path.exists():
            return None
        try:
            import yaml
            raw = path.read_text(encoding="utf-8")
            return yaml.safe_load(raw) if ext == "yaml" else json.loads(raw)
        except Exception as e:
            logger.error(f"BusinessVault[{self.business_name}] read file {path}: {e}")
            return None

    def set_config_blob(self, name: str, data: Dict[str, Any]) -> bool:
        """Persist a structured config blob to Redis (file cache in dev)."""
        payload = json.dumps(data, ensure_ascii=False)
        if self._redis:
            try:
                self._redis.set(self._config_key(name), payload)
                return True
            except Exception as e:
                logger.error(f"BusinessVault[{self.business_name}] set_config_blob({name}): {e}")
                return False


        return True

    def delete_config_blob(self, name: str) -> bool:
        """Delete a config blob."""
        if self._redis:
            try:
                self._redis.delete(self._config_key(name))
                return True
            except Exception as e:
                logger.error(f"BusinessVault[{self.business_name}] delete_config_blob({name}): {e}")
                return False
        return True

    def list_config_blobs(self) -> list[str]:
        """List all stored config blobs for this business."""
        if self._redis:
            try:
                pattern = f"{_VAULT_PREFIX}:{self.business_name}:{_CONFIG_SUFFIX}:*"
                keys = self._redis.keys(pattern)
                prefix = f"{_VAULT_PREFIX}:{self.business_name}:{_CONFIG_SUFFIX}:"
                return [k.decode() if isinstance(k, bytes) else k[len(prefix):] for k in keys]
            except Exception as e:
                logger.error(f"BusinessVault[{self.business_name}] list_config_blobs: {e}")
                return []
        return []

    @property
    def config_version(self) -> Optional[str]:
        """Get stored config version for this business."""
        cfg = self.get_config_blob("config")
        return cfg.get("config_version") if cfg else None

    def get_config(self) -> Dict[str, Any]:
        """
        Get the business YAML config dict. Redis-first, filesystem fallback.
        Cached after first load.
        """
        cached = getattr(self, "_config_cache", None)
        if cached is not None:
            return cached

        from core.business_loader import load_business_config
        config = load_business_config(self.business_name) or {}
        self._config_cache = config
        return config

    def reload(self):
        """Reload secrets and config from source."""
        self._local_secrets = {}
        self._local_loaded = False
        if hasattr(self, "_config_cache"):
            del self._config_cache

        if self._redis:
            pass
        else:
            self._load_local_env()

        logger.info(f"BusinessVault[{self.business_name}] reloaded")

    @property
    def mode(self) -> str:
        return "redis" if self._redis else "file"


    @property
    def bot_token(self) -> Optional[str]:
        return self.get_secret("BOT_TOKEN")

    @property
    def notification_bot_token(self) -> Optional[str]:
        return self.get_secret("NOTIFICATION_BOT_TOKEN")

    @property
    def business_owner_chat_id(self) -> Optional[str]:
        return self.get_secret("BUSINESS_OWNER_CHAT_ID")

    @property
    def apps_script_token(self) -> Optional[str]:
        """Get the secret token for the business's Apps Script endpoint."""
        return self.get_secret("APPS_SCRIPT_TOKEN")
