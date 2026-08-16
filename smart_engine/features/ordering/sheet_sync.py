"""
SheetSyncManager — Google Apps Script → products.json sync.

Each business deploys their own Apps Script bound to their sheet.
The script exposes a GET endpoint that returns product JSON when
called with the business's secret token.

No GCP billing. No OAuth2. Just HTTP.
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

PRODUCTS_FILENAME = "products.json"


KEY_MAP: dict[str, str] = {
    "product name": "name",
    "name": "name",
    "item": "name",
    "price": "price",
    "cost": "price",
    "amount": "price",
    "description": "description",
    "desc": "description",
    "details": "description",
    "category": "category",
    "cat": "category",
    "type": "category",
    "quantity": "max_quantity",
    "stock": "max_quantity",
    "qty": "max_quantity",
    "bookable": "bookable",
    "synonyms": "aliases",
    "aliases": "aliases",
    "keywords": "aliases",
}


class SheetSyncManager:

    def __init__(self, business_name: str) -> None:
        self.business_name = business_name
        self._products_path = Path("businesses") / business_name / PRODUCTS_FILENAME
        self._config: dict = {}
        self._load_config()


    def _load_config(self) -> None:
        from core.business_loader import load_business_config
        cfg = load_business_config(self.business_name) or {}
        self._config = cfg.get("inventory_source") or {}

    @property
    def apps_script_url(self) -> Optional[str]:
        return self._config.get("apps_script_url")

    @property
    def is_apps_script(self) -> bool:
        return self._config.get("type") == "apps_script"

    @property
    def sync_interval_minutes(self) -> int:
        return self._config.get("sync_interval_minutes", 60)


    def _get_token(self) -> Optional[str]:
        from core.business_vault import BusinessVault
        vault = BusinessVault(self.business_name)
        return vault.get_secret("APPS_SCRIPT_TOKEN")


    def fetch_products(self) -> Optional[List[Dict]]:
        """GET the Apps Script endpoint and normalize product rows.

        Returns None on any failure — caller falls back to cached products.json.
        """
        url = self.apps_script_url
        if not url:
            logger.warning(f"[{self.business_name}] No apps_script_url in inventory_source config")
            return None

        token = self._get_token()
        if not token:
            logger.warning(f"[{self.business_name}] No APPS_SCRIPT_TOKEN in vault")
            return None

        import requests
        try:
            resp = requests.get(url, params={"token": token}, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.warning(f"[{self.business_name}] Apps Script fetch failed: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"[{self.business_name}] Apps Script returned invalid JSON: {e}")
            return None

        if not isinstance(data, list):
            logger.warning(f"[{self.business_name}] Apps Script returned non-array: {type(data)}")
            return None

        if not data:
            logger.info(f"[{self.business_name}] Apps Script returned empty product list")
            return []


        products: List[Dict] = []
        for i, row in enumerate(data):
            if not isinstance(row, dict):
                continue
            product = self._normalize_row(row, i)
            if product:
                products.append(product)

        logger.info(f"[{self.business_name}] Fetched {len(products)} raw rows from Apps Script")
        grouped = self._group_variants(products)
        logger.info(f"[{self.business_name}] Grouped into {len(grouped)} products (with variants)")
        return grouped

    def _normalize_row(self, row: Dict[str, Any], index: int) -> Optional[Dict]:
        """Normalize an Apps Script row dict to internal flat format.

        Extracts Variant Name alongside all other fields. Grouping into
        has_variants / variants[] happens in _group_variants().
        """
        def get_val(*keys: str) -> str:
            for k in keys:
                val = row.get(k, "")
                if val:
                    return str(val).strip()
            return ""

        name = get_val("Product Name", "product name", "name", "Name", "item", "Item")
        if not name:
            logger.debug(f"[{self.business_name}] Skipping row {index}: empty name")
            return None

        price_raw = get_val("Price", "price", "Cost", "cost", "Amount", "amount")
        try:
            import re
            clean = re.sub(r'[^\d.\-]', '', price_raw) if price_raw else ""
            price = float(clean) if clean else 0.0
        except (ValueError, TypeError):
            price = 0.0

        quantity_raw = get_val("Quantity", "quantity", "Stock", "stock", "Qty", "qty")
        try:
            max_quantity = int(float(quantity_raw)) if quantity_raw else 999
        except (ValueError, TypeError):
            max_quantity = 999

        bookable_raw = get_val("Bookable", "bookable").lower()
        bookable = bookable_raw in ("yes", "true", "y", "1")

        aliases_raw = get_val("Synonyms", "synonyms", "Aliases", "aliases", "Keywords", "keywords")
        aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()] if aliases_raw else []

        variant_name = get_val("Variant Name", "variant name", "variant", "Variant")

        product = {
            "name": name,
            "price": price,
            "variant_name": variant_name,
            "description": get_val("Description", "description", "Desc", "desc", "Details", "details"),
            "category": get_val("Category", "category", "Cat", "cat", "Type", "type") or "Uncategorized",
            "available": max_quantity > 0,
            "bookable": bookable,
            "max_quantity": max_quantity,
        }
        if aliases:
            product["aliases"] = aliases

        return product

    @staticmethod
    def _group_variants(flat_products: List[Dict]) -> List[Dict]:
        """Group flat rows by product name into a variant-aware structure.

        Rows with the same Product Name are merged:
          - If any row has a non-empty Variant Name → has_variants: true,
            variants: [{name, price, ...}, ...]
          - Otherwise → has_variants: false, price = first row's price
        """
        from collections import OrderedDict
        grouped: Dict[str, Dict[str, Any]] = OrderedDict()

        for row in flat_products:
            key = (row["category"], row["name"])
            if key not in grouped:
                grouped[key] = {
                    "name": row["name"],
                    "category": row["category"],
                    "description": row["description"],
                    "available": row["available"],
                    "bookable": row.get("bookable", False),
                    "max_quantity": row.get("max_quantity", 999),
                    "has_variants": False,
                    "price": row["price"],
                    "variants": [],
                    "_raw_variants": [],
                }
                if "aliases" in row:
                    grouped[key]["aliases"] = row["aliases"]

            variant_name = row.get("variant_name", "").strip()
            if variant_name:
                grouped[key]["has_variants"] = True
                grouped[key]["_raw_variants"].append({
                    "name": variant_name,
                    "price": row["price"],
                })
            elif not grouped[key]["description"] and row["description"]:

                grouped[key]["description"] = row["description"]


        result: List[Dict] = []
        for key, prod in grouped.items():
            if prod["has_variants"]:
                prod["variants"] = sorted(prod.pop("_raw_variants"), key=lambda v: v["price"])
                prod.pop("price", None)
            else:
                prod.pop("_raw_variants")
                prod.pop("variants", None)
            result.append(prod)

        return result


    def sync(self) -> bool:
        """Fetch from Apps Script and atomically write products.json.

        Returns True on success, False on failure (caller uses cached file).
        """
        if not self.is_apps_script:
            return False

        products = self.fetch_products()
        if products is None:
            logger.warning(
                f"[{self.business_name}] Apps Script fetch failed — keeping cached products.json"
            )
            self._update_last_sync("failed")
            return False

        try:
            tmp_path = self._products_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(str(tmp_path), str(self._products_path))
            logger.info(
                f"[{self.business_name}] Synced {len(products)} products to {self._products_path}"
            )
            self._update_last_sync("ok")
            return True
        except Exception as e:
            logger.error(f"[{self.business_name}] Failed to write products.json: {e}")
            self._update_last_sync(f"error: {e}")
            return False

    def _update_last_sync(self, status: str) -> None:
        try:
            import yaml
            config_path = Path("businesses") / self.business_name / "business_config.yaml"
            if not config_path.exists():
                return
            raw = config_path.read_text(encoding="utf-8")
            cfg = yaml.safe_load(raw) or {}
            src = cfg.setdefault("inventory_source", {})
            src["last_sync"] = datetime.now(timezone.utc).isoformat()
            src["last_sync_status"] = status
            config_path.write_text(
                yaml.dump(cfg, default_flow_style=False, allow_unicode=True), encoding="utf-8"
            )
        except Exception as e:
            logger.debug(f"[{self.business_name}] Could not update last_sync in config: {e}")


    @staticmethod
    def test_sheet_access(apps_script_url: str, token: str) -> dict:
        """Verify an Apps Script URL returns valid product data.

        Returns {"ok": True, "columns": [...], "row_count": N}
        or      {"ok": False, "error": "..."}
        """
        import requests
        try:
            resp = requests.get(apps_script_url, params={"token": token}, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            return {"ok": False, "error": f"Request failed: {e}"}
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"Invalid JSON: {e}"}

        if not isinstance(data, list) or not data:
            return {"ok": False, "error": "Empty or invalid product list"}

        columns = list(data[0].keys()) if isinstance(data[0], dict) else []
        return {
            "ok": True,
            "columns": columns,
            "row_count": len(data),
        }
