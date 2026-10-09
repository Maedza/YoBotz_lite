# Changelog

All notable changes to YoBotz are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- **Stale tool state trapping users in fallback responses**: when an ordering or booking flow completed, `active_tool` was never removed from the session file. A stale tool caused the router to skip intent prediction and route every message (e.g. "hi") into the inactive tool, producing "I didn't understand that." The chat engine and router now detect stale tool state (`ordering_state` not ORDERING / `booking_flow.active` False), clear and persist the fix before prediction.
- **State-aware fallbacks for active tools**: while a tool is genuinely active, unparseable messages now return a reminder of the current flow state (ordering category menu / booking context-aware fallback) instead of a generic "I didn't understand that."
- **`auto_setup_gateway.py` silent startup failures**: ngrok output was discarded (`DEVNULL`), so a failed tunnel produced a blank terminal and a 60s silent wait. Output is now captured, a dead process is detected immediately with its output logged, and progress is reported while waiting.
- **`llm_response_generator.py` broken under Python 3.9**: f-string expressions contained backslash escapes (PEP 701, Python 3.12+ syntax), which failed to compile under the project's 3.9 venv. Placeholder rules are now precomputed outside the f-string; leftover literal code text embedded in the prompt was removed, and the previously undefined `num_responses` is now a real variable.
- **Crash-safe runtime file creation**: `BookingManager` now resolves the business directory from the project root (was cwd-relative, so it broke when launched from another working directory), creates missing parent directories, and tolerates missing/corrupted `bookings.json` / `locks.json` by treating them as empty instead of crashing.
- **README Quick Start**: replaced placeholder repo URL with `https://github.com/Maedza/YoBotz_lite.git` and fixed `YoBotz_Lite` → `YoBotz_lite` casing in Quick Start and Project Structure sections.
- **README `.env` example**: removed hardcoded `BUSINESS_OWNER_CHAT_ID=987654321` from the per-business env example; replaced with `<owner_chat_id>` placeholder.
- **Router adapter lookup order**: webhook handler now tries per-business `bot_token` adapter first and falls back to the base adapter, instead of requiring the base adapter first. Multi-bot setups no longer need a system-level `TELEGRAM_BOT_TOKEN`; per-business tokens registered via BusinessVault are sufficient.
- **Order notification timestamp timezone**: `_send_order_notification` now uses the business-configured `timezone` (from `business_config.yaml`) instead of naive `datetime.now()` (server local time). Order `order_id` and `timestamp` fields are both derived from the same business-local moment.

### Security
- **Runtime data no longer committed**: `businesses/**/bookings.json` and `businesses/**/locks.json` are now gitignored and removed from version control. These files are auto-created at runtime and contain business-local operational data.
