"""Loads and formats responses from business YAML files."""
import os
import yaml
from datetime import datetime
from smart_engine.core.utils.response_channel import BotReply
import logging

logger = logging.getLogger(__name__)


class ResponseHandler:
    def __init__(self, business_name: str):
        self.business_name = business_name
        self.responses = self.load_responses()
        self.display_name = self._load_display_name()
        self.business_hours = self._load_business_hours()
        self.contact_info = self._load_contact_info()

    def load_responses(self) -> dict:
        path = os.path.join("businesses", self.business_name, "responses.yaml")
        if not os.path.exists(path):
            logger.warning("responses.yaml not found for '%s'", self.business_name)
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_display_name(self) -> str:
        cfg_path = os.path.join("businesses", self.business_name, "business_config.yaml")
        if not os.path.exists(cfg_path):
            return self.business_name.replace("_", " ").title()
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("display_name", self.business_name.replace("_", " ").title())

    def _load_business_hours(self) -> dict:
        try:
            cfg_path = os.path.join("businesses", self.business_name, "business_config.yaml")
            if not os.path.exists(cfg_path):
                return {}
            with open(cfg_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            return config.get("business_hours", {})
        except Exception:
            return {}

    def _load_contact_info(self) -> dict:
        """Load contact info from business config."""
        try:
            cfg_path = os.path.join("businesses", self.business_name, "business_config.yaml")
            if not os.path.exists(cfg_path):
                return {}
            with open(cfg_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}

            contact = config.get("contact", config)
            return {
                "address": contact.get("address", ""),
                "phone": contact.get("phone", ""),
                "email": contact.get("email", ""),
            }
        except Exception:
            return {}

    def _format_business_hours(self) -> str:
        if not self.business_hours:
            return "Business hours not configured."
        days_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        lines = []
        for day_key, day_name in zip(days_order, day_names):
            day_slots = self.business_hours.get(day_key)
            if day_slots:
                slot_strs = [f"{s.get('open', '??:??')}-{s.get('close', '??:??')}" for s in day_slots]
                lines.append(f"**{day_name}:** {', '.join(slot_strs)}")
            else:
                lines.append(f"**{day_name}:** Closed")
        return "\n".join(lines)

    def _get_open_status(self) -> str:
        if not self.business_hours:
            return "⏳ Open status unavailable"
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        day_key = days[datetime.now().weekday()]
        day_slots = self.business_hours.get(day_key)
        if not day_slots:
            return "⏳ We're CLOSED today"
        now = datetime.now().time()
        for slot in day_slots:
            try:
                open_t = datetime.strptime(slot.get("open", "00:00"), "%H:%M").time()
                close_t = datetime.strptime(slot.get("close", "00:00"), "%H:%M").time()
                if open_t <= now <= close_t:
                    return "✅ We're OPEN!"
            except ValueError:
                continue
        return "⏳ We're CLOSED"

    def get_response(self, key: str, **kwargs) -> str:
        """Fetch and format a response from YAML."""
        resp = self.responses.get(key)
        if resp is None:
            return f"[{key}] response missing"

        text = resp[0] if isinstance(resp, list) else resp


        import re
        placeholders = re.findall(r'\{(\w+)\}', text)
        format_kwargs = dict(kwargs)
        format_kwargs.setdefault("business_name", self.display_name)

        if "business_hours" not in format_kwargs:
            format_kwargs["business_hours"] = self._format_business_hours()
        if "is_open_now" not in format_kwargs:
            format_kwargs["is_open_now"] = self._get_open_status()


        _placeholder_values = {
            "hours": self._format_business_hours(),
            "address": self.contact_info.get("address", "Address not configured"),
            "phone": self.contact_info.get("phone", "Phone not configured"),
            "email": self.contact_info.get("email", "Email not configured"),
        }
        for key, value in _placeholder_values.items():
            text = re.sub(r'\{\{\s*' + re.escape(key) + r'\s*\}\}', value, text)


        for ph in placeholders:
            format_kwargs.setdefault(ph, f"[{ph} missing]")

        try:
            return text.format(**format_kwargs)
        except KeyError as e:
            logger.warning("Missing placeholder: %s", e)
            return text
        except Exception as e:
            logger.error("Format error for '%s': %s", key, e)
            return text

    def fallback(self) -> BotReply:
        return BotReply(self.get_response("fallback"), meta={"intent": "fallback"})

    def has_intent_response(self, intent: str) -> bool:
        key = f"intent_{intent}"
        return self.responses.get(key) not in (None, "")
