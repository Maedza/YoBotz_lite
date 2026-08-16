"""
Unified Messaging Gateway Server

Main FastAPI server that handles all platform webhooks and routing.
"""

import os
import time
import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from .config import load_config
from .models import UnifiedMessage, DeliveryStatus
from .router import MessageRouter
from .user_mapper import UserMapper
from .delivery_tracker import DeliveryTracker
from .message_queue import MessageQueue
from .adapters import TelegramAdapter
from core.business_registry import BusinessRegistry


import os
from logging.handlers import RotatingFileHandler


logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)


log_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'logs')
os.makedirs(log_dir, exist_ok=True)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            os.path.join(log_dir, 'unified_gateway.log'),
            maxBytes=10*1024*1024,
            backupCount=5
        )
    ]
)
logger = logging.getLogger(__name__)


config = None
router = None
user_mapper = None
delivery_tracker = None
message_queue = None
business_registry = None


startup_time = None


_bot_token_to_business: dict = {}


_last_hot_reload_time: float = 0.0
_hot_reload_cooldown: float = 60.0


_last_webhook_failure_time = {}
_webhook_failure_cooldown = 300  # 5 minutes per platform
_last_queue_size_notification_time = None
_queue_size_notification_cooldown = 600  # 10 minutes for queue alerts


_sheet_sync_task: Optional[asyncio.Task] = None


async def _sheet_sync_loop():
    """Background task: sync all Apps Script businesses every 5 minutes."""
    SYNC_INTERVAL = 300
    while True:
        try:
            await asyncio.sleep(SYNC_INTERVAL)
            if not business_registry:
                continue
            from smart_engine.features.ordering.sheet_sync import SheetSyncManager
            for biz_name in business_registry.list_businesses():
                try:
                    mgr = SheetSyncManager(biz_name)
                    if mgr.is_apps_script:
                        mgr.sync()
                except Exception as e:
                    logger.debug(f"Sheet sync skipped for '{biz_name}': {e}")
        except asyncio.CancelledError:
            logger.info("Sheet sync loop cancelled")
            break
        except Exception as e:
            logger.warning(f"Sheet sync loop error: {e}")


async def _auto_setup_webhooks(public_url: str, discovered: list):
    """Auto-configure Telegram webhooks for all businesses on cloud deploy."""
    import aiohttp

    secret_token = os.getenv("TELEGRAM_WEBHOOK_SECRET")

    for biz_name in discovered:
        try:
            vault = business_registry.get_vault(biz_name)
            if not vault or not vault.bot_token:
                logger.warning(f"Skipping webhook for '{biz_name}': no bot token in vault")
                continue

            webhook_url = f"{public_url}/telegram/webhook/{vault.bot_token}"
            api_url = f"https://api.telegram.org/bot{vault.bot_token}/setWebhook"
            payload = {"url": webhook_url, "drop_pending_updates": True}
            if secret_token:
                payload["secret_token"] = secret_token

            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=payload, timeout=15) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        logger.info(f"✓ Webhook set for '{biz_name}': {webhook_url}")
                    else:
                        logger.error(
                            f"✗ Webhook failed for '{biz_name}': {data.get('description')}"
                        )
        except Exception as e:
            logger.error(f"✗ Webhook setup error for '{biz_name}': {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    global config, router, user_mapper, delivery_tracker, message_queue, startup_time, business_registry


    logger.info("Starting Unified Messaging Gateway...")
    startup_time = datetime.now()


    config = load_config()
    logger.info(f"Configuration loaded: Port={config.port}, Log Level={config.log_level}")


    business_registry = BusinessRegistry(config.redis_url)
    discovered = business_registry.discover_all()
    logger.info(f"BusinessRegistry discovered {len(discovered)} businesses: {discovered}")


    storage_backend = "redis" if config.redis_url else "json"


    user_mapper = UserMapper(
        storage_backend=storage_backend,
        storage_path=config.redis_url if storage_backend == "redis" else None
    )
    if storage_backend == "json":
        logger.info(f"UserMapper initialized (backend=json)")
    else:
        logger.info(f"UserMapper initialized (backend=redis - checking connection...)")


    if config.redis_url:
        message_queue = MessageQueue(config.redis_url)
        logger.info("MessageQueue initialized (Redis - will try to connect)")
    else:
        message_queue = None
        logger.warning("MessageQueue disabled (no Redis URL configured)")


    delivery_tracker = DeliveryTracker(
        storage_backend=storage_backend,
        storage_path=config.redis_url if storage_backend == "redis" else None,
        retry_config={
            "max_attempts": config.delivery_retry_max_attempts,
            "base_delay": config.delivery_retry_base_delay,
            "max_delay": config.delivery_retry_max_delay
        }
    )
    if storage_backend == "json":
        logger.info(f"DeliveryTracker initialized (backend=json)")
    else:
        logger.info(f"DeliveryTracker initialized (backend=redis - checking connection...)")


    router = MessageRouter(user_mapper, lazy_business_loading=True)
    router.register_delivery_tracker("telegram", delivery_tracker)


    global _bot_token_to_business
    _bot_token_to_business = {}
    for biz_name in discovered:
        try:
            vault = business_registry.get_vault(biz_name)
            if vault and vault.bot_token:
                _bot_token_to_business[vault.bot_token] = biz_name
                logger.info(f"Mapped bot token to business: {biz_name}")
        except Exception as e:
            logger.warning(f"Could not get vault for {biz_name}: {e}")


    from smart_engine.core.chat_engine import ChatEngine
    for biz_name in discovered:
        try:
            engine = ChatEngine(biz_name)
            router.register_business(biz_name, engine)
            logger.info(f"Registered business engine: {biz_name}")
        except Exception as e:
            logger.error(f"Failed to initialize ChatEngine for {biz_name}: {e}")


    if config.telegram.enabled:
        telegram_adapter = TelegramAdapter(config.telegram)
        router.register_adapter("telegram", telegram_adapter)
        logger.info("Telegram base adapter registered")

    logger.info("Unified Messaging Gateway started successfully")


    public_url = os.getenv("PUBLIC_URL")
    if public_url:
        if not public_url.startswith("http"):
            public_url = f"https://{public_url}"
        logger.info(f"Public URL detected: {public_url} — auto-configuring Telegram webhooks")
        await _auto_setup_webhooks(public_url, discovered)
    else:
        logger.info("No public URL detected (local/dev mode) — skipping webhook auto-setup")
    try:
        from notification_system.service import get_notification_service
        notification_service = get_notification_service()
        logger.info("Attempting to send server started notification...")
        result = await notification_service.send_server_started(config.default_business)
        if result:
            logger.info("Server started notification sent successfully")
        else:
            logger.warning("Server started notification failed (no recipients or Telegram error)")
    except Exception as e:
        logger.warning(f"Could not send server started notification: {e}")
        logger.warning("Check that DEVELOPER_CHAT_ID is set in .env and notification bot is configured")


    try:
        from notification_system.scheduler import start_scheduler
        from notification_system.service import get_notification_service
        notification_service = get_notification_service()
        scheduler = await start_scheduler(notification_service)
        logger.info("✅ Notification scheduler started in background")


        if not hasattr(lifespan, '_scheduler_task'):
            lifespan._scheduler_task = scheduler
    except Exception as e:
        logger.warning(f"Could not start notification scheduler: {e}")


    global _sheet_sync_task
    _sheet_sync_task = asyncio.create_task(_sheet_sync_loop())
    logger.info("Sheet sync background task started")

    yield


    logger.info("Shutting down Unified Messaging Gateway...")


    try:
        if hasattr(lifespan, '_scheduler_task'):
            scheduler = lifespan._scheduler_task
            if scheduler and hasattr(scheduler, 'stop'):
                await scheduler.stop()
                logger.info("Notification scheduler stopped")
    except Exception as e:
        logger.warning(f"Error stopping scheduler: {e}")


    if _sheet_sync_task:
        _sheet_sync_task.cancel()
        try:
            await _sheet_sync_task
        except asyncio.CancelledError:
            pass
        logger.info("Sheet sync background task stopped")


    for platform_name, adapter in router.platform_adapters.items():
        if hasattr(adapter, 'close'):
            await adapter.close()

    logger.info("Unified Messaging Gateway stopped")


app = FastAPI(
    title="YoBotz Unified Messaging Gateway",
    description="Unified messaging gateway for Telegram",
    version="1.0.0",
    lifespan=lifespan
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Health check endpoint"""
    if startup_time:
        uptime = str(datetime.now() - startup_time).split('.')[0]
    else:
        uptime = "unknown"

    return {
        "status": "healthy",
        "version": "1.0.0",
        "platforms": list(router.platform_adapters.keys()) if router else [],
        "businesses": list(router.business_engines.keys()) if router else [],
        "uptime": uptime,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Telegram webhook endpoint (legacy - uses default/primary bot)"""
    global _last_webhook_failure_time

    if not router:
        raise HTTPException(status_code=503, detail="Gateway not initialized")

    headers = dict(request.headers)
    body = await request.json()

    logger.debug("Received Telegram webhook (legacy endpoint)")

    try:
        t0 = time.time()
        response = await router.handle_webhook("telegram", headers, body)
        elapsed_ms = int((time.time() - t0) * 1000)

        logger.info(f"webhook legacy {elapsed_ms}ms")
        return JSONResponse(content={"status": "ok"})

    except ValueError as e:
        logger.error(f"✗ Webhook verification failed: {e}")
        raise HTTPException(status_code=403, detail=str(e))

    except Exception as e:
        logger.error(f"✗ Error processing Telegram webhook: {e}", exc_info=True)


        try:
            from notification_system.service import get_notification_service
            service = get_notification_service()


            now = datetime.now()
            last_time = _last_webhook_failure_time.get("telegram")
            if last_time is None or (now - last_time).total_seconds() > _webhook_failure_cooldown:
                _last_webhook_failure_time["telegram"] = now
                await service.send_webhook_failure("telegram", str(e), str(body)[:200])
        except ImportError:
            pass
        except Exception as notify_error:
            logger.warning(f"Failed to send webhook failure notification: {notify_error}")

        return JSONResponse(content={"status": "error", "error": str(e)}, status_code=500)


@app.post("/telegram/webhook/{bot_token}")
async def telegram_webhook_per_bot(bot_token: str, request: Request):
    """
    Telegram webhook endpoint for multi-bot support.

    Each bot has its own webhook URL: /telegram/webhook/{bot_token}
    The bot_token is used to route to the correct business/bot adapter.
    """
    global _last_webhook_failure_time, _bot_token_to_business, business_registry, _last_hot_reload_time

    if not router:
        raise HTTPException(status_code=503, detail="Gateway not initialized")

    headers = dict(request.headers)
    body = await request.json()


    now = time.time()
    if business_registry and (now - _last_hot_reload_time) >= _hot_reload_cooldown:
        _last_hot_reload_time = now
        try:
            new_businesses = business_registry.discover_all()
            for biz_name in new_businesses:
                if biz_name not in _bot_token_to_business.values():
                    vault = business_registry.get_vault(biz_name)
                    if vault and vault.bot_token:
                        _bot_token_to_business[vault.bot_token] = biz_name
                        from smart_engine.core.chat_engine import ChatEngine
                        engine = ChatEngine(biz_name)
                        router.register_business(biz_name, engine)
                        logger.info(f"Hot-reload: registered new business '{biz_name}'")
        except Exception as e:
            logger.warning(f"Hot-reload scan failed: {e}")


    business_name = _bot_token_to_business.get(bot_token)

    if not business_name:

        try:
            for biz in business_registry.list_businesses():
                vault = business_registry.get_vault(biz)
                if vault and vault.bot_token == bot_token:
                    business_name = biz
                    _bot_token_to_business[bot_token] = biz
                    logger.info(f"Found business '{biz}' for bot token via vault lookup")
                    break
        except Exception as e:
            logger.warning(f"Could not search vaults for bot token: {e}")

    if not business_name:
        logger.warning(f"Unknown bot token: {bot_token[:10]}...")
        raise HTTPException(status_code=404, detail="Bot token not registered")

    try:

        t0 = time.time()
        response = await router.handle_webhook(
            "telegram", headers, body,
            bot_token=bot_token,
            business_name=business_name
        )
        elapsed_ms = int((time.time() - t0) * 1000)

        logger.info(f"webhook {business_name} {elapsed_ms}ms")
        return JSONResponse(content={"status": "ok"})

    except ValueError as e:
        logger.error(f"✗ Webhook verification failed: {e}")
        raise HTTPException(status_code=403, detail=str(e))

    except Exception as e:
        logger.error(f"✗ Error processing Telegram webhook for '{business_name}': {e}", exc_info=True)


        try:
            from notification_system.service import get_notification_service
            service = get_notification_service()

            now = datetime.now()
            last_time = _last_webhook_failure_time.get(bot_token)
            if last_time is None or (now - last_time).total_seconds() > _webhook_failure_cooldown:
                _last_webhook_failure_time[bot_token] = now
                await service.send_webhook_failure(f"telegram:{business_name}", str(e), str(body)[:200])
        except ImportError:
            pass
        except Exception as notify_error:
            logger.warning(f"Failed to send webhook failure notification: {notify_error}")

        return JSONResponse(content={"status": "error", "error": str(e)}, status_code=500)


@app.get("/status")
async def status():
    """Get gateway status"""
    global _last_queue_size_notification_time

    if not router:
        return {
            "status": "not_initialized",
            "platforms": [],
            "businesses": []
        }

    router_status = router.get_status()

    queue_sizes = {}
    if message_queue:
        queue_sizes = await message_queue.get_queue_size()


        try:
            from notification_system.service import get_notification_service
            service = get_notification_service()

            total_size = queue_sizes.get("pending", 0) + queue_sizes.get("retry", 0) + queue_sizes.get("dead_letter", 0)
            if total_size > 100:
                now = datetime.now()
                if _last_queue_size_notification_time is None or \
                   (now - _last_queue_size_notification_time).total_seconds() > _queue_size_notification_cooldown:
                    _last_queue_size_notification_time = now
                    await service.send_message_queue_status(total_size)
        except ImportError:
            pass
        except Exception as notify_error:
            logger.warning(f"Failed to send queue size notification: {notify_error}")

    return {
        "status": "running",
        "router": router_status,
        "queue_sizes": queue_sizes,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "YoBotz Unified Messaging Gateway",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "telegram_webhook": "/telegram/webhook",
            "status": "/status",
            "admin_businesses": "/admin/businesses",
            "admin_reload": "/admin/reload",
            "onboarding": "/onboarding/*",
            "sheet_authorize": "/admin/{business_name}/authorize-sheet",
            "sheet_verify": "/onboarding/verify-sheet",
            "sheet_sync": "/admin/{business_name}/sync-products",
        },
        "documentation": "See UNIFIED_MESSAGING_DESIGN.md for details"
    }


def _generate_config_blobs_from_onboarding(onboarding_data: dict) -> dict:
    """
    Convert onboarding form data into Redis-ready config blobs.
    Used when onboarding a business directly via admin API.
    """
    import json as _json
    import yaml as _yaml
    from onboarding.generators import (
        generate_business_config,
        generate_responses,
        generate_products_json,
        generate_services_yaml,
        CATEGORY_DEFAULTS,
    )

    cat_defaults = CATEGORY_DEFAULTS.get(onboarding_data.get("category", "generic"), {})
    complete_data = {**cat_defaults, **onboarding_data}

    blobs = {}

    try:
        raw = generate_business_config(complete_data)
        blobs["config"] = _yaml.safe_load(raw)
    except Exception as e:
        logger.warning(f"Failed to generate config blob: {e}")

    try:
        raw = generate_responses(complete_data)
        blobs["responses"] = _yaml.safe_load(raw)
    except Exception as e:
        logger.warning(f"Failed to generate responses blob: {e}")

    features = onboarding_data.get("features", {})
    if features.get("ordering") and onboarding_data.get("product_source", "static") != "apps_script":
        try:
            blobs["products"] = _json.loads(generate_products_json(complete_data))
        except Exception as e:
            logger.warning(f"Failed to generate products blob: {e}")

    if features.get("booking") or (
        features.get("ordering") and features.get("ordering_mode") == "reservation"
    ):
        try:
            blobs["services"] = _yaml.safe_load(generate_services_yaml(complete_data))
        except Exception as e:
            logger.warning(f"Failed to generate services blob: {e}")

    return blobs


@app.get("/admin/businesses")
async def admin_list_businesses():
    """List all registered businesses."""
    if not business_registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")
    return {"businesses": business_registry.list_businesses()}


@app.post("/admin/businesses")
async def admin_register_business(request: Request):
    """
    Onboard a new business.

    Body:
        business_name: str
        secrets: dict of key-value pairs (written to vault)
        webhook_url: optional Telegram webhook URL
        onboarding_data: optional dict — full form data used to generate
            config blobs (config, responses, products, services).
    """
    if not business_registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    business_name = body.get("business_name")
    secrets = body.get("secrets", {})
    webhook_url = body.get("webhook_url")
    onboarding_data = body.get("onboarding_data")

    if not business_name:
        raise HTTPException(status_code=400, detail="business_name is required")
    if not isinstance(secrets, dict):
        raise HTTPException(status_code=400, detail="secrets must be a dict")

    config_blobs = None
    if onboarding_data:
        config_blobs = _generate_config_blobs_from_onboarding(onboarding_data)

    result = business_registry.register_business(
        business_name, secrets, webhook_url, config_blobs
    )


    from smart_engine.core.chat_engine import ChatEngine
    try:
        engine = ChatEngine(business_name)
        router.register_business(business_name, engine)
        logger.info(f"Admin: registered engine for newly onboarded '{business_name}'")
    except Exception as e:
        logger.warning(f"Admin: failed to register engine for '{business_name}': {e}")

    return {"status": "ok", **result}


@app.get("/admin/businesses/{business_name}")
async def admin_get_business(business_name: str):
    """Get secrets keys (not values) and config for a business."""
    if not business_registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")

    vault = business_registry.get_vault(business_name)
    if not vault:
        raise HTTPException(status_code=404, detail=f"Business '{business_name}' not found")

    return {
        "business_name": business_name,
        "secret_keys": vault.list_secrets(),
        "config": vault.get_config(),
        "mode": vault.mode
    }


@app.put("/admin/businesses/{business_name}/secrets")
async def admin_update_secrets(business_name: str, request: Request):
    """Update secrets for a business (partial update)."""
    if not business_registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")

    vault = business_registry.get_vault(business_name)
    if not vault:
        raise HTTPException(status_code=404, detail=f"Business '{business_name}' not found")

    try:
        secrets = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(secrets, dict):
        raise HTTPException(status_code=400, detail="Body must be a dict")

    for key, value in secrets.items():
        vault.set_secret(key, str(value))

    return {"status": "ok", "business_name": business_name, "updated": list(secrets.keys())}


@app.delete("/admin/businesses/{business_name}")
async def admin_deregister_business(business_name: str):
    """Deregister a business."""
    if not business_registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")

    business_registry.deregister_business(business_name)
    return {"status": "ok", "business_name": business_name}


@app.post("/admin/reload")
async def admin_reload(request: Request):
    """
    Hot-reload one or all businesses.

    Body (optional): {"business_name": "yo_bakery"}  -- omit for full reload
    """
    if not business_registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")

    try:
        body = await request.json()
        business_name = body.get("business_name")
    except Exception:
        business_name = None

    result = business_registry.reload(business_name)
    return {"status": "ok", **result}


from onboarding.routes import router as onboarding_router
app.include_router(onboarding_router)


@app.post("/onboarding/verify-sheet")
async def verify_sheet(request: Request):
    """Verify that an Apps Script endpoint returns valid product data."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    apps_script_url = body.get("apps_script_url", "")
    token = body.get("token", "")
    if not apps_script_url:
        raise HTTPException(status_code=400, detail="apps_script_url is required")
    if not token:
        raise HTTPException(status_code=400, detail="token is required")

    from smart_engine.features.ordering.sheet_sync import SheetSyncManager
    result = SheetSyncManager.test_sheet_access(apps_script_url, token)
    return result


@app.post("/admin/{business_name}/sync-products")
async def sync_products(business_name: str):
    """Manually trigger a product sync from Apps Script."""
    if not business_registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")

    vault = business_registry.get_vault(business_name)
    if not vault:
        raise HTTPException(status_code=404, detail=f"Business '{business_name}' not found")

    from smart_engine.features.ordering.sheet_sync import SheetSyncManager
    mgr = SheetSyncManager(business_name)
    if not mgr.is_apps_script:
        raise HTTPException(status_code=400, detail="Business does not use Apps Script")

    success = mgr.sync()
    return {"status": "ok" if success else "failed", "business_name": business_name}


if __name__ == "__main__":
    import uvicorn


    cfg = load_config()


    uvicorn.run(
        "unified_gateway.server:app",
        host="0.0.0.0",
        port=cfg.port,
        log_level="warning",
        access_log=False
    )
