# YoBotz Lite Progress Tracking

Session-by-session log of changes, fixes, and decisions.

---

## 2026-08-16 — Log Monitoring Path Fix

**Issue:** The notification system's log monitor still pointed at legacy log files (`telegram_bot.log`, `smart_engine.log`) and a hardcoded v1.2 base path, so it never read the live runtime log.

**Changes:**
- `notification_system/config.py` — default config switched to the real `log_monitor.enabled/files` structure; fallback log file is now `unified_gateway.log`
- `notification_system/data_collector.py` — `base_dir` derived from `__file__` (project root) instead of a hardcoded `/Users/mac/Desktop/YoBotz_Beta_v1.2`; all log readers now read `data/logs/unified_gateway.log`

**Files touched:** `notification_system/config.py`, `notification_system/data_collector.py`

---

## 2026-07-23 — Product Variants + Search Command

**Changes:**

### 1. Product Variants System
Products can now have variants (e.g., "6 inch" vs "12 inch" cakes at different prices):
- `sheet_sync.py`: added `Variant Name` column support → `_group_variants()` merges rows with same product name into a `variants: [{name, price}]` structure
- `ordering_enums.py`: new `OrderSubState.AWAITING_VARIANT_SELECTION` state
- `ordering_manager.py`: `_show_variant_menu()`, `_handle_variant_selection()`, `add_to_cart()` accepts optional `variant` param — stores as `"Product Name (Variant Name)"` in cart
- `product_handler.py`: `_build_smart_product_menu()` groups products by base name, shows `(N variants)` label with `min_price`–`max_price` range
- `responses.yaml`: new `variant_selection_prompt` template
- `start_ordering()` and `complete_order()` now clear `ordering_selected_product`/`ordering_selected_quantity` from session

### 2. Product Search Command
Users can type `search [query]` or `find [query]` to find products by substring match:
- `model_handler.py`: detects `"search "`/`"find "` prefix → adds `product_search` intent
- `ordering_intent_handler.py`: routes `product_search` intent → starts ordering flow
- `ordering_manager.py`: `_handle_search_command()` — scoped to current category or all products; scores by exact-start match then substring; capped at 10 results
- `product_handler.py`: `search_products()` — substring match on `name` + `aliases`, sorted by relevance
- Works in both `AWAITING_PRODUCT_SELECTION` (scoped) and general state (all products)

### 3. Sheet Sync Enhancements
- `sheet_sync.py`: new `Variant Name` column in schema; `_group_variants()` uses `OrderedDict` keyed by (category, name); non-variant rows merge description if empty; variants sorted by price
- `landing page/sheet-setup.html`: "Variant Name" column documented in column table; "Required?" column added for clarity

### 4. Response & UX Updates
- `responses.yaml`: `intent_help` & `intent_fallback` now mention `search [name]` command; `product_menu_prompt` reworded to "Browse our selection"; `product_selection_fallback` mentions search; `category_selection_fallback` removed
- Refactored: `_find_product()` removed (logic inlined into `_handle_product_selection`)

### 5. Housekeeping
- `.gitignore`: added `data/notification_chat_ids.json` and `data/user_mappings_fallback.json` runtime files

**Files touched:** `ordering_manager.py`, `product_handler.py`, `sheet_sync.py`, `ordering_intent_handler.py`, `ordering_enums.py`, `model_handler.py`, `responses.yaml`, `sheet-setup.html`, `.gitignore`

---

## 2026-06-26 — Flexible Placeholder Matching

**Changes:**
- `response_handler.py`: replaced 4 hardcoded `if "{{hours}}" in text` checks with a single regex loop — `\{\{\s*key\s*\}\}` matches `{{hours}}`, `{{ hours }}`, `{{  hours  }}`, etc.
- `onboarding/llm_response_generator.py`: added `_normalize_placeholders()` — collapses whitespace variants AND single-brace variants (`{phone}` → `{{phone}}`) to clean format at generation time, before validation checks
- Extensible: add new placeholder keys to one dict, not 4 new if-blocks

**Files touched:** `response_handler.py`, `llm_response_generator.py`

---

## Major Features

### 1. Google Sheets Sync
Pull product inventory directly from Google Sheets via Apps Script — no GCP billing, no OAuth2.
- `smart_engine/features/ordering/sheet_sync.py` — SheetSyncManager: fetch → normalize → cache to `products.json`
- `landing page/setup.html` — inline sheet URL input during business setup
- `onboarding/generators.py` — `inventory_source:` block in generated `business_config.yaml`
- Offline resilient: always falls back to last cached `products.json`

### 2. BusinessVault — Multi-Tenant Secrets
Per-business secrets isolation with dual-mode storage (Redis / `.env` files).
- `core/business_vault.py` — `get_secret/set_secret/list_secrets` + convenience accessors
- `core/business_registry.py` — auto-discovery of `businesses/` dir, hot-reload, admin CRUD endpoints
- Telegram webhook auto-setup per business, per-biz notification tokens

### 3. Landing Page + Setup Wizard
- `landing page/index.html` — public landing page with embedded chat widget
- `landing page/setup.html` — multi-step business setup (branding → features → AI responses → ordering)
- Theme-aware CSS, localStorage conversation persistence

### 4. Customer Onboarding Flow
- `onboarding/` — 6-step wizard: Welcome → Name → Phone → Email → Preferences → Confirmation
- Token-based session verification, LLM-powered response generation per business category

### 5. Placeholder System
- `{{hours}}`, `{{address}}`, `{{phone}}`, `{{email}}` in `responses.yaml`
- Replaced at runtime from `business_config.yaml` — config changes auto-propagate
- LLM hardcoded values detected and fixed automatically

### 6. Multi-Bot Webhook Support
- Each business gets its own Telegram webhook, notification bot token, and chat IDs

---

## 2026-06-26 — Sheet Sync Price & JSON Format Fixes

**Changes:**
- `sheet_sync.py`: strip currency symbols before `float()` — fixed all prices being `$0.00`
- `generators.py`: output plain `[...]` array instead of `{"products":[...]}` — matches `ProductHandler` expectations
- `product_handler.py`: accept both list and `{"products":[...]}` dict formats as fallback

**Files touched:** `sheet_sync.py`, `generators.py`, `product_handler.py`

---

## 2026-06-26 — iCloud Cleanup + Session Exit Review

**Changes:**
- Deleted all `.icloud` iCloud placeholder files and `"file 2"` conflict duplicates
- `.gitignore`: added `*.icloud` rule

**Session exit:** Confirmed both ordering and booking emit `tool_completed: True` → router pops `active_tool`. "bye" is a `goodbye` intent — text only, no session clearing (correct).

---

## 2026-04-07 — Help Command & Session Fixes

**Changes:**
- Added "help" keyword detection in `IntentRouter` fallback section
- Session clearing revert — "bye" in global exit commands caused issues

---
