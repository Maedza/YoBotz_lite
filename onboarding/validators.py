"""
Onboarding step validators.
Each step validates its input and returns errors if any.
"""

import re
from typing import Any


class ValidationError(Exception):
    """Raised when validation fails."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(str(errors))


CATEGORY_CHOICES = ["restaurant", "bakery", "retail", "salon", "clinic", "generic"]
FEATURE_CHOICES = ["ordering", "booking", "reservation", "accounts", "inventory"]
TIMEZONE_CHOICES = [
    "Asia/Singapore", "Asia/Kuala_Lumpur", "Asia/Hong_Kong",
    "Asia/Tokyo", "Asia/Seoul", "Asia/Bangkok",
    "America/New_York", "America/Los_Angeles", "America/Chicago",
    "America/Toronto", "America/Vancouver",
    "Europe/London", "Europe/Paris", "Europe/Berlin",
    "Australia/Sydney", "Australia/Melbourne",
]


def validate_step(step: int, data: dict) -> dict[str, str]:
    """
    Validate data for a given step.
    Returns dict of field -> error message. Empty dict = valid.
    """
    validators = {
        1: _validate_basic_info,
        2: _validate_features,
        3: _validate_contact,
        4: _validate_operational,
        5: _validate_secrets,
    }

    validator = validators.get(step)
    if not validator:
        return {}

    return validator(data)


def _validate_basic_info(data: dict) -> dict[str, str]:
    errors = {}


    name = data.get("name", "").strip()
    if not name:
        errors["name"] = "Business name is required"
    elif not re.match(r"^[a-z0-9_]+$", name):
        errors["name"] = "Name must be lowercase letters, numbers, underscores only"
    elif len(name) < 3:
        errors["name"] = "Name must be at least 3 characters"
    elif len(name) > 50:
        errors["name"] = "Name must be under 50 characters"


    display_name = data.get("display_name", "").strip()
    if not display_name:
        errors["display_name"] = "Display name is required"
    elif len(display_name) > 100:
        errors["display_name"] = "Display name must be under 100 characters"


    category = data.get("category", "").strip()
    if not category:
        errors["category"] = "Category is required"
    elif category not in CATEGORY_CHOICES:
        errors["category"] = f"Invalid category. Choose from: {', '.join(CATEGORY_CHOICES)}"


    description = data.get("description", "").strip()
    if description and len(description) > 500:
        errors["description"] = "Description must be under 500 characters"

    return errors


def _validate_features(data: dict) -> dict[str, str]:
    errors = {}
    features = data.get("features", {})

    if not isinstance(features, dict):
        errors["features"] = "Features must be an object"
        return errors

    for key in features:
        if key not in FEATURE_CHOICES:
            errors[f"features.{key}"] = f"Unknown feature: {key}"


    if features.get("reservation") and not features.get("ordering"):
        errors["features.reservation"] = "Reservation Mode requires Ordering System to be enabled"

    return errors


def _validate_contact(data: dict) -> dict[str, str]:
    errors = {}


    timezone = data.get("timezone", "").strip()
    if timezone and timezone not in TIMEZONE_CHOICES:
        errors["timezone"] = f"Invalid timezone. Choose from: {', '.join(TIMEZONE_CHOICES)}"


    hours_pattern = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
    for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        for period in ["open", "close"]:
            key = f"hours_{day}_{period}"
            val = data.get(key, "").strip()
            if val and not hours_pattern.match(val):
                errors[key] = f"Invalid time format. Use HH:MM (e.g., 09:00)"


    phone = data.get("phone", "").strip()
    if phone and not re.match(r"^[\d\s\+\-\(\)]+$", phone):
        errors["phone"] = "Invalid phone number format"


    email = data.get("email", "").strip()
    if email and not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        errors["email"] = "Invalid email format"

    return errors


def _validate_operational(data: dict) -> dict[str, str]:
    errors = {}


    if data.get("features", {}).get("ordering"):
        min_order = data.get("min_order_amount")
        if min_order is not None:
            try:
                val = float(min_order)
                if val < 0:
                    errors["min_order_amount"] = "Minimum order amount cannot be negative"
            except (TypeError, ValueError):
                errors["min_order_amount"] = "Must be a valid number"


    if data.get("features", {}).get("booking") or data.get("features", {}).get("reservation"):
        for key in ["min_booking_notice", "max_booking_lead_days"]:
            val = data.get(key)
            if val is not None:
                try:
                    int_val = int(val)
                    if int_val < 0:
                        errors[key] = "Cannot be negative"
                except (TypeError, ValueError):
                    errors[key] = "Must be a whole number"

    return errors


def _validate_secrets(data: dict) -> dict[str, str]:
    errors = {}


    bot_token = data.get("BOT_TOKEN", "").strip()
    if not bot_token:
        errors["BOT_TOKEN"] = "Bot token is required"
    elif not re.match(r"^\d+:[A-Za-z0-9_-]+$", bot_token):
        errors["BOT_TOKEN"] = "Invalid Telegram bot token format (should be like 123456789:ABCdef...)"


    chat_id_pattern = re.compile(r"^-?\d+$")
    for key in ["BUSINESS_OWNER_CHAT_ID"]:
        val = data.get(key, "").strip()
        if val and not chat_id_pattern.match(val):
            errors[key] = "Invalid chat ID format (must be numeric)"

    return errors
