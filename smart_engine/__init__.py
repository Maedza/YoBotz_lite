import logging
import os

logging.getLogger("smart_engine").setLevel(
    logging.DEBUG
    if os.getenv("DEBUG", "false").lower() in ("1", "true")
    else getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
)
