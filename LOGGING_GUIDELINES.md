# Logging Guidelines

Consistent logging across the YoBotz Lite codebase: clean, actionable, maintainable.

## Setup

Every module declares its own logger:

```python
import logging

logger = logging.getLogger(__name__)
```

Levels are configured centrally in `smart_engine/__init__.py`:

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug logging (`1`/`true`) | `false` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |

```bash
# Production
LOG_LEVEL=INFO

# Development
DEBUG=1
```

Records propagate to the app's root handlers (`logging.basicConfig` in `unified_gateway/server.py`), so all logs land in the same stdout + file handlers.

Use the module logger — never `print()` or custom debug helpers.

## Levels

| Level | Use for |
|-------|---------|
| `CRITICAL` | App crashes, unrecoverable system-wide failures |
| `ERROR` | Failed operations that need attention (API/db/file failures). Not for expected conditions with fallbacks |
| `WARNING` | Potentially harmful but non-blocking (missing optional deps, deprecated features) |
| `INFO` | Significant business events (orders, bookings), service lifecycle (startup/shutdown), connections established |
| `DEBUG` | Routine diagnostics, state changes, function entry/exit, variable states |

## Message Format

```python
logger.info("[Module] Action description: key=value, key2=value2")
```

```python
logger.info("[OrderingManager] Order created: order_id=123, total=$45.50")
logger.error("[Database] Query failed: error='connection timeout', query='SELECT * FROM orders'")
logger.debug("[ChatEngine] Processing: user=123, intent='booking', conf=0.95")
```

- Bad: too verbose (`Function called with parameters: user_id=..., ...`), missing context (`Something went wrong`), too cryptic (`Processing...`).

## Rules

- **No emojis** — they break log aggregators and consistency.
- **Consolidate related logs** into one line:

```python
# Bad
logger.debug("Starting to process order")
logger.debug(f"Order ID: {order_id}")
logger.debug(f"Total: ${total}")

# Good
logger.debug(f"Processing order: id={order_id}, total=${total}")
```

- **Don't log in loops** — log a summary around them.
- **No redundant success logs** — one success log per operation.
- **Don't log sensitive data** — passwords, tokens, API keys, personal customer info.
- **Correct severity** — expected conditions go to DEBUG, real failures to ERROR:

```python
# Bad: expected condition as WARNING
if not self.service:
    logger.warning("Service not available")

# Good
if not self.service:
    logger.debug("Service not available - using fallback")
```

- **Use lazy string formatting**: `logger.debug(f"Value: {x}")`, not `%`-formatting.

## Log Files

- Location: `data/logs/unified_gateway.log` (gateway's `RotatingFileHandler`)
- Rotation: 10 MB per file, 5 backups (`maxBytes=10*1024*1024`, `backupCount=5`)
- The gateway attaches a `StreamHandler` and a `RotatingFileHandler` to the root logger

```bash
# Count errors
grep "ERROR" data/logs/unified_gateway.log | wc -l

# Errors by module
grep "ERROR" data/logs/unified_gateway.log | cut -d'[' -f2 | cut -d']' -f1 | sort | uniq -c

# Real-time monitoring
tail -f data/logs/unified_gateway.log | grep --line-buffered -E "ERROR|CRITICAL"
```
