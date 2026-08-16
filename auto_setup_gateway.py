#!/usr/bin/env python3
"""Quick-setup launcher: start ngrok tunnel + gateway server in one command.

Starts an ngrok tunnel, then boots the unified gateway with PUBLIC_URL set so
the server auto-configures Telegram webhooks on startup. Press Ctrl+C to stop
both processes cleanly. Requires ngrok (macOS: brew install ngrok).
"""

import logging
import os
import subprocess
import sys
import time

import requests
from dotenv import load_dotenv

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
load_dotenv(os.path.join(project_root, ".env"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("quick_setup")

PORT = int(os.getenv("PORT", "8000"))


def start_ngrok():
    """Start ngrok tunnel on the gateway port. Returns the process or None."""
    try:
        subprocess.run(["ngrok", "version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("ngrok not found. Install it with: brew install ngrok")
        return None
    return subprocess.Popen(
        ["ngrok", "http", str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def get_ngrok_url(max_attempts=30, retry_delay=2):
    """Wait for ngrok API and return the public tunnel URL."""
    for _ in range(max_attempts):
        try:
            tunnels = requests.get(
                "http://127.0.0.1:4040/api/tunnels", timeout=5
            ).json().get("tunnels")
            if tunnels:
                return tunnels[0]["public_url"]
        except requests.RequestException:
            pass
        time.sleep(retry_delay)
    return None


def main():
    ngrok = start_ngrok()
    if not ngrok:
        return 1

    server = None
    try:
        url = get_ngrok_url()
        if not url:
            logger.error("Failed to obtain ngrok URL")
            return 1
        logger.info("Public URL: %s", url)

        env = {**os.environ, "PUBLIC_URL": url}
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "unified_gateway.server:app",
             "--host", "0.0.0.0", "--port", str(PORT)],
            env=env,
        )
        server.wait()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        if server:
            server.terminate()
        ngrok.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
