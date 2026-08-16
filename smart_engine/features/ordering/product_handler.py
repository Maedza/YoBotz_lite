import os
import json
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

SMART_DISPLAY_LIMIT = 5

class ProductHandler:

    def __init__(self, business_name: str):
        self.business_name = business_name
        self.products = self.load_products()

    def load_products(self) -> List[Dict]:
        path = os.path.join("businesses", self.business_name, "products.json")
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    products = data.get("products", [])
                    if isinstance(products, list):
                        return products
                return []
            except Exception as e:
                logger.exception(f"[ProductHandler] Failed to load products.json for '{self.business_name}': {e}")
                return []

    def reload(self) -> None:
        self.products = self.load_products()

    def get_products(self) -> List[Dict]:
        return self.products

    def get_categories(self) -> Dict[str, Dict]:
        categories = {}
        for product in self.products:
            cat = product.get("category", "Uncategorized")
            if cat not in categories:
                categories[cat] = {"order": len(categories) + 1}
        return categories

    def get_products_by_category(self, category: str) -> List[Dict]:
        return [p for p in self.products if p.get("category") == category]


    @staticmethod
    def _extract_base_model(product_name: str) -> str:
        """Strip variant parenthetical info to get the base model name.

        'iPhone 15 Pro (128GB)' → 'iPhone 15 Pro'
        'Sourdough Bread'       → 'Sourdough Bread'
        """
        if '(' in product_name:
            return product_name.split('(')[0].strip()
        return product_name

    def get_unique_models_by_category(self, category: str) -> List[Dict]:
        """Return unique base models in a category with variant count and min price.

        Products with the same base model name (after stripping variant suffixes)
        are merged into one entry showing variant count and price range.

        Returns list of dicts:
          {display_name, base_name, products, variant_count, min_price, max_price, has_variants}
        """
        products = self.get_products_by_category(category)
        if not products:
            return []

        grouped: Dict[str, List[Dict]] = {}
        for p in products:
            base = self._extract_base_model(p["name"])
            grouped.setdefault(base, []).append(p)

        result = []
        for base_name, group in grouped.items():
            all_variants = []
            for p in group:
                if p.get("has_variants") and p.get("variants"):
                    all_variants.extend(p["variants"])
                else:
                    all_variants.append({"name": base_name, "price": p.get("price", 0)})

            prices = [v["price"] for v in all_variants]
            total_variants = len(all_variants)
            first_product = group[0]

            display_name = base_name
            if len(group) > 1 or total_variants > 1:
                display_name = f"{base_name} ({total_variants} variants)"

            result.append({
                "display_name": display_name,
                "base_name": base_name,
                "products": group,
                "variant_count": total_variants,
                "min_price": min(prices),
                "max_price": max(prices),
                "has_variants": len(group) > 1 or group[0].get("has_variants", False),
                "category": first_product.get("category", category),
                "description": first_product.get("description", ""),
                "available": any(p.get("available", True) for p in group),
            })

        return sorted(result, key=lambda m: m["base_name"].lower())


    def search_products(self, query: str, category: Optional[str] = None, limit: int = 10) -> List[Dict]:
        query_lower = query.lower()
        products = self.get_products_by_category(category) if category else self.products
        results = []
        for p in products:
            name_lower = p["name"].lower()
            aliases_lower = " ".join(p.get("aliases", [])).lower()
            if query_lower in name_lower or (aliases_lower and query_lower in aliases_lower):
                results.append(p)


        def _score(p: Dict) -> int:
            name = p["name"].lower()
            if name.startswith(query_lower):
                return 0
            if query_lower in name:
                return 1
            return 2

        results.sort(key=_score)
        return results[:limit]
