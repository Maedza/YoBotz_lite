"""
Minimal feature toggle service for pricing tiers.
"""
from core.business_loader import load_business_config
import logging

logger = logging.getLogger(__name__)

class FeatureToggle:
    def __init__(self, business_name: str):
        self.business_name = business_name
        self.config = load_business_config(business_name) or {}
        logger.debug(f"[FEATURE] Loaded config for {business_name}")

    def reload_config(self):
        """Reload config from file (for runtime updates)"""
        self.config = load_business_config(self.business_name) or {}
        logger.info(f"[FEATURE] Reloaded config for {self.business_name}")
        features = self.config.get("features", {})
        logger.info(f"[FEATURE] Ordering: {features.get('enable_ordering_system', True)}, Booking: {features.get('enable_booking_system', True)}")

    def is_ordering_enabled(self) -> bool:
        """Master switch for entire ordering system"""
        features = self.config.get("features", {})
        enabled = features.get("enable_ordering_system", True)
        logger.info(f"[FEATURE] Checking ordering enabled: {enabled}")
        return enabled

    def is_booking_enabled(self) -> bool:
        """Master switch for entire booking system"""
        features = self.config.get("features", {})
        enabled = features.get("enable_booking_system", True)
        logger.debug("Checking booking enabled: %s", enabled)
        return enabled

    def get_system_message(self, system: str) -> str:
        """Get clean 'service unavailable' message"""
        messages = {
            "ordering": "Sorry, this business currently doesn't support online ordering. Type 'help' to see what we offer.",
            "booking": "Sorry, this business currently doesn't support online booking. Type 'help' to see what we offer."
        }
        msg = messages.get(system, "This system is not currently available.")
        logger.info(f"[FEATURE] Returning system message for '{system}': {msg}")
        return msg


_toggle_cache = {}

def get_feature_toggle(business_name: str, reload: bool = False) -> FeatureToggle:
    """Get or create feature toggle instance.

    Args:
        business_name: Business name
        reload: Force reload config from file (default: False)
    """
    if reload or business_name not in _toggle_cache:
        _toggle_cache[business_name] = FeatureToggle(business_name)
    return _toggle_cache[business_name]

def reload_feature_toggle(business_name: str):
    """Force reload config for a business.

    Args:
        business_name: Business name
    """
    if business_name in _toggle_cache:
        _toggle_cache[business_name].reload_config()
    else:
        _toggle_cache[business_name] = FeatureToggle(business_name)
