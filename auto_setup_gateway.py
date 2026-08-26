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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def get_ngrok_url(ngrok, max_attempts=45, retry_delay=2):
    """Wait for ngrok API and return the public tunnel URL."""
    for attempt in range(max_attempts):
        if ngrok.poll() is not None:
            output = ngrok.stdout.read() if ngrok.stdout else ""
            logger.error(
                "ngrok process exited early (code %s). Output:\n%s",
                ngrok.returncode,
                output.strip() or "(no output)",
            )
            return None
        try:
            tunnels = requests.get(
                "http://127.0.0.1:4040/api/tunnels", timeout=5
            ).json().get("tunnels")
            if tunnels:
                return tunnels[0]["public_url"]
        except requests.RequestException:
            pass
        if attempt and attempt % 5 == 0:
            logger.info("Waiting for ngrok tunnel... (%ds)", attempt * retry_delay)
        time.sleep(retry_delay)
    return None


def main():
    ngrok = start_ngrok()
    if not ngrok:
        return 1

    server = None
    try:
        url = get_ngrok_url(ngrok)
        if not url:
            logger.error("Failed to obtain ngrok URL")
            if ngrok.poll() is None:
                logger.error(
                    "ngrok is still running but no tunnel appeared. Check network "
                    "connectivity or run `ngrok http %s` manually to see the error.",
                    PORT,
                )
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
