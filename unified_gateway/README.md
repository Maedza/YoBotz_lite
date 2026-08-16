# Unified Gateway

The unified gateway is the single entry point for all inbound and outbound platform traffic. It owns every webhook, adapter, and message delivery path — no other component talks to Telegram (or any future platform) directly.

## Responsibilities

| Component | Role |
|-----------|------|
| `server.py` | FastAPI application: webhooks, health, status, admin API, onboarding API |
| `router.py` | `MessageRouter` — orchestrates `handle_webhook → route_message → send_message` |
| `adapters/` | Platform adapters (`base.py`, `telegram.py`): `receive_message()` and `send_message()` |
| `message_queue.py` | Optional Redis-backed async processing (falls back to inline processing) |
| `delivery_tracker.py` | Tracks send status per message |
| `user_mapper.py` | Maps platform user IDs to internal identities |
| `models.py` | Unified message model shared across platforms |

## Message Flow

```
Client → server.py webhook
      → router.handle_webhook()
        → adapter.receive_message(raw)      # raw → UnifiedMessage
        → route_message(message)            # → ChatEngine.process_message() → BotReply
      → router.send_message(response)       # inline, same request
        → adapter.send_message(reply)       # → platform API
```

Replies are sent inline within the webhook request; there is no outbound queue in the default configuration.

## Endpoints

### Public

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Service info (version, registered businesses, uptime) |
| `GET` | `/health` | Health check with business registry and startup status |
| `GET` | `/status` | Gateway status, queue state, notification status |
| `POST` | `/telegram/webhook` | Telegram webhook (legacy — default/primary bot) |
| `POST` | `/telegram/webhook/{bot_token}` | Telegram webhook for multi-bot support |

### Admin

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/admin/businesses` | List registered businesses |
| `POST` | `/admin/businesses` | Register/onboard a new business |
| `GET` | `/admin/businesses/{business_name}` | Business config + secret keys (values hidden) |
| `PUT` | `/admin/businesses/{business_name}/secrets` | Partial update of vault secrets |
| `DELETE` | `/admin/businesses/{business_name}` | Deregister a business |
| `POST` | `/admin/reload` | Hot-reload one or all businesses |
| `POST` | `/admin/{business_name}/sync-products` | Manually trigger product sync from Apps Script |

### Onboarding

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/onboarding/verify-sheet` | Verify an Apps Script endpoint returns valid product data |

> **Note**: Admin endpoints have no authentication in the current build. Put the gateway behind a reverse proxy, VPN, or add auth before exposing it publicly.

## Running

```bash
python3 -m uvicorn unified_gateway.server:app --host 0.0.0.0 --port 8000
```

See `auto_setup_gateway.py` for one-command launch with an ngrok tunnel and automatic Telegram webhook registration.

## Logging

The gateway configures root logging in `server.py`: console output plus a rotating file at `data/logs/unified_gateway.log` (10 MB per file, 5 backups). See [LOGGING_GUIDELINES.md](../LOGGING_GUIDELINES.md).
