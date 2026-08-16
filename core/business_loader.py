"""
Business data loader with Redis-first strategy.

All load_*() functions check Redis first (persistent across server restarts),
fall back to the local filesystem (git-tracked), and auto-sync filesystem
discoveries into Redis for future reads.

Config versioning: CURRENT_CONFIG_VERSION defines the code's expected config
format. When a business config loaded from Redis has an older version,
``migrate_config()`` upgrades it transparently. This allows gradual rollouts
— existing businesses stay on their current version until (a) they're
explicitly updated via API, or (b) a migration bumps them forward.
"""

import os
import time
import json
import yaml
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

CURRENT_CONFIG_VERSION = "1.0.0"
_CONFIG_CACHE_TTL = 5


_REGISTRY_KEY = "biz:_registry"


def _get_redis_client():
    """Return a Redis client if REDIS_URL is configured and reachable."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return None
    try:
        import redis
        client = redis.from_url(redis_url)
        client.ping()
        return client
    except Exception:
        return None


_vault_cache: Dict[str, Any] = {}

def _get_vault(business_name: str):
    """Lazy-import BusinessVault to avoid circular imports. Cached per-business."""
    if business_name not in _vault_cache:
        from core.business_vault import BusinessVault
        _vault_cache[business_name] = BusinessVault(business_name)
    return _vault_cache[business_name]


def migrate_config(config: Dict[str, Any],
                   from_version: str,
                   to_version: str = CURRENT_CONFIG_VERSION) -> Dict[str, Any]:
    """
    Upgrade a business config from an older version to the current version.

    Migration steps are additive and idempotent — safe to re-run.
    Returns the migrated config dict (mutates input for efficiency).
    """
    if from_version == to_version:
        return config

    logger.debug(
        f"Migrating config from v{from_version} → v{to_version}"
    )


    config["config_version"] = to_version
    return config


def list_businesses() -> List[str]:
    """
    List all available businesses.

    Merges Redis registry (API-onboarded) with filesystem (git-tracked).
    Returns sorted unique list.
    """
    names = set()


    try:
        businesses_dir = "businesses"
        if os.path.exists(businesses_dir):
            for item in os.listdir(businesses_dir):
                biz_path = os.path.join(businesses_dir, item)
                if os.path.isdir(biz_path) and not item.startswith('.'):
                    config_file = os.path.join(biz_path, "business_config.yaml")
                    if os.path.exists(config_file):
                        names.add(item)
    except Exception as e:
        logger.error(f"Error scanning businesses directory: {e}")


    redis = _get_redis_client()
    if redis:
        try:
            raw = redis.get(_REGISTRY_KEY)
            if raw:
                redis_names = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                names.update(redis_names)
        except Exception as e:
            logger.warning(f"Failed to read Redis registry: {e}")

    return sorted(names)


_config_cache: Dict[str, tuple] = {}

def load_business_config(business_name: str) -> Optional[Dict[str, Any]]:
    """
    Load business config. Redis-first, filesystem fallback.
    Cached for 5s to avoid redundant calls from multiple modules per request.
    """
    now = time.time()
    cached = _config_cache.get(business_name)
    if cached and (now - cached[1]) < _CONFIG_CACHE_TTL:
        return cached[0]

    vault = _get_vault(business_name)


    config = vault.get_config_blob("config")
    if config:
        version = config.get("config_version", "0.0.0")
        if version != CURRENT_CONFIG_VERSION:
            config = migrate_config(config, version, CURRENT_CONFIG_VERSION)
            vault.set_config_blob("config", config)
            vault.set_secret("config_version", CURRENT_CONFIG_VERSION)


        config = _expand_vars(config, business_name)
        return config


    try:
        config_path = os.path.join("businesses", business_name, "business_config.yaml")
        if not os.path.exists(config_path):
            logger.warning(f"Business config not found: {config_path}")
            return None

        with open(config_path, 'r', encoding='utf-8') as f:
            raw = f.read()

        raw_expanded = _expand_raw_vars(raw, business_name)
        config = yaml.safe_load(raw_expanded) or {}


        if "config_version" not in config:
            config["config_version"] = CURRENT_CONFIG_VERSION
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    original = f.read()
                if "config_version:" not in original:
                    with open(config_path, 'a', encoding='utf-8') as f:
                        f.write(f"\nconfig_version: \"{CURRENT_CONFIG_VERSION}\"\n")
            except Exception:
                pass


        vault.set_config_blob("config", config)
        vault.set_secret("config_version", CURRENT_CONFIG_VERSION)

        _config_cache[business_name] = (config, now)
        return config

    except Exception as e:
        logger.error(f"Error loading business config for {business_name}: {e}")
        return None


def load_business_responses(business_name: str) -> Optional[Dict[str, Any]]:
    """Load business responses. Redis-first, filesystem fallback."""
    vault = _get_vault(business_name)


    responses = vault.get_config_blob("responses")
    if responses:
        return responses


    try:
        responses_path = os.path.join("businesses", business_name, "responses.yaml")
        if not os.path.exists(responses_path):
            logger.warning(f"Business responses not found: {responses_path}")
            return None

        with open(responses_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        vault.set_config_blob("responses", data)
        return data

    except Exception as e:
        logger.error(f"Error loading business responses for {business_name}: {e}")
        return None


def load_business_products(business_name: str) -> Optional[List[Dict[str, Any]]]:
    """Load business products. Redis-first, filesystem fallback."""
    vault = _get_vault(business_name)


    products = vault.get_config_blob("products")
    if products:

        if isinstance(products, dict) and "products" in products:
            return products["products"]
        if isinstance(products, list):
            return products
        return products


    try:
        products_path = os.path.join("businesses", business_name, "products.json")
        if not os.path.exists(products_path):
            logger.warning(f"Business products not found: {products_path}")
            return None

        with open(products_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        vault.set_config_blob("products", raw)

        if isinstance(raw, dict) and "products" in raw:
            return raw["products"]
        if isinstance(raw, list):
            return raw
        return raw

    except Exception as e:
        logger.error(f"Error loading business products for {business_name}: {e}")
        return None


def load_business_services(business_name: str) -> Optional[Dict[str, Any]]:
    """Load business services. Redis-first, filesystem fallback."""
    vault = _get_vault(business_name)


    services = vault.get_config_blob("services")
    if services:
        return services


    try:
        services_path = os.path.join("businesses", business_name, "services.yaml")
        if not os.path.exists(services_path):
            logger.warning(f"Business services not found: {services_path}")
            return None

        with open(services_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        vault.set_config_blob("services", data)
        return data

    except Exception as e:
        logger.error(f"Error loading business services for {business_name}: {e}")
        return None


def validate_business_structure(business_name: str) -> bool:
    """
    Validate that a business has the required structure.
    Checks Redis first (API-registered), then filesystem (git-tracked).
    """

    vault = _get_vault(business_name)
    if vault.get_config_blob("config"):
        return True


    try:
        business_path = os.path.join("businesses", business_name)
        if not os.path.exists(business_path):
            return False

        required = ["business_config.yaml", "responses.yaml"]
        for fname in required:
            if not os.path.exists(os.path.join(business_path, fname)):
                return False
        return True

    except Exception as e:
        logger.error(f"Error validating business {business_name}: {e}")
        return False


def get_business_info(business_name: str) -> Optional[Dict[str, Any]]:
    """Get comprehensive business info."""
    if not validate_business_structure(business_name):
        return None

    config = load_business_config(business_name)
    if not config:
        return None

    return {
        "name": business_name,
        "config": config,
        "responses": load_business_responses(business_name),
        "products": load_business_products(business_name),
        "services": load_business_services(business_name),
    }


def sync_all_to_redis() -> Dict[str, Any]:
    """
    Push all filesystem business configs into Redis.
    Called once during migration or after first Redis setup.
    """
    result = {"synced": [], "skipped": [], "errors": []}
    for name in list_businesses():
        try:
            vault = _get_vault(business_name=name)

            if vault.mode != "redis":
                result["skipped"].append(name)
                continue

            for blob_name in ("config", "responses", "products", "services"):
                existing = vault.get_config_blob(blob_name)
                if existing:
                    continue
                data = _load_raw_file(name, blob_name)
                if data is not None:
                    vault.set_config_blob(blob_name, data)

            result["synced"].append(name)
            logger.info(f"Synced '{name}' configs to Redis")
        except Exception as e:
            result["errors"].append({"business": name, "error": str(e)})
            logger.error(f"Sync failed for '{name}': {e}")

    return result


def _load_raw_file(business_name: str, blob_name: str) -> Optional[Any]:
    """Load a raw file without expansion, for syncing to Redis."""
    _FS_FILENAME = {
        "config": "business_config", "responses": "responses",
        "products": "products", "services": "services",
    }
    _FS_EXT = {"config": "yaml", "responses": "yaml", "products": "json", "services": "yaml"}
    fname = _FS_FILENAME.get(blob_name, blob_name)
    ext = _FS_EXT.get(blob_name, "json")
    path = os.path.join("businesses", business_name, f"{fname}.{ext}")
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        if ext == "json":
            return json.load(f)
        return yaml.safe_load(f) or {}


def _expand_raw_vars(raw_text: str, business_name: str) -> str:
    """Expand ${VAR} placeholders in raw YAML text."""
    import re
    vault = _get_vault(business_name)

    def replace(m):
        var = m.group(1) or m.group(2)
        try:
            val = vault.get_secret(var)
            if val:
                return val
        except Exception:
            pass
        return os.getenv(var, m.group(0))

    return re.sub(r'\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)', replace, raw_text)


def _expand_vars(config: dict, business_name: str) -> dict:
    """Walk config dict and expand ${VAR} placeholders."""
    import re
    vault = _get_vault(business_name)

    def walk(obj):
        if isinstance(obj, str):
            def replace(m):
                var = m.group(1) or m.group(2)
                try:
                    val = vault.get_secret(var)
                    if val:
                        return val
                except Exception:
                    pass
                return os.getenv(var, m.group(0))
            return re.sub(r'\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)', replace, obj)
        elif isinstance(obj, dict):
            return {k: walk(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [walk(item) for item in obj]
        return obj

    return walk(config)
