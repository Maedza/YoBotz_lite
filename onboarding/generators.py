"""
Onboarding config generators — YAML/JSON file generation.
Refactored from scaffold_business.py for API use.
Includes LLM-powered response generation.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


try:
    from .llm_response_generator import generate_responses_with_llm, enhance_with_llm
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    logger.warning("LLM response generator not available, using template fallback")
    generate_responses_with_llm = None
    enhance_with_llm = None


CATEGORY_DEFAULTS = {
    "restaurant": {
        "currency": "USD",
        "tax_rate": 0.0875,
        "order_term": "Order",
        "product_term": "Dish",
        "cart_term": "Order",
        "hours_open": "09:00",
        "hours_close": "18:00",
    },
    "bakery": {
        "currency": "USD",
        "tax_rate": 0.0875,
        "order_term": "Order",
        "product_term": "Pastry",
        "cart_term": "Order",
        "hours_open": "08:00",
        "hours_close": "17:00",
    },
    "retail": {
        "currency": "USD",
        "tax_rate": 0.08,
        "order_term": "Purchase",
        "product_term": "Product",
        "cart_term": "Cart",
        "hours_open": "10:00",
        "hours_close": "20:00",
    },
    "salon": {
        "currency": "USD",
        "tax_rate": 0.08,
        "booking_term": "Appointment",
        "service_term": "Service",
        "hours_open": "10:00",
        "hours_close": "19:00",
    },
    "clinic": {
        "currency": "USD",
        "tax_rate": 0.0,
        "booking_term": "Appointment",
        "service_term": "Treatment",
        "hours_open": "09:00",
        "hours_close": "17:00",
    },
    "generic": {
        "currency": "USD",
        "tax_rate": 0.0,
        "hours_open": "09:00",
        "hours_close": "18:00",
    },
}


def generate_business_config(data: dict) -> str:
    """Generate business_config.yaml content."""
    f = data.get("features", {})
    ordering = f.get("ordering", False)
    booking = f.get("booking", False)
    accounts = f.get("accounts", False)
    inventory = f.get("inventory", False)
    ordering_mode = f.get("ordering_mode", "cart")
    is_reservation_mode = ordering and ordering_mode == "reservation"

    namings = _build_namings(data)
    cat_defaults = CATEGORY_DEFAULTS.get(data.get("category", "generic"), {})


    hours = _build_hours(data, cat_defaults)

    from core.business_loader import CURRENT_CONFIG_VERSION

    cfg = f"""# =============================
# {data['display_name']} Business Configuration
# =============================
name: {data['name']}
display_name: "{data['display_name']}"
description: "{data.get('description', '')}"

business_category: "{data['category']}"
config_version: "{CURRENT_CONFIG_VERSION}"

# =============================
# FEATURES
# =============================
features:
  enable_ordering_system: {str(ordering).lower()}
  enable_booking_system: {str(booking).lower()}
  enable_customer_accounts: {str(accounts).lower()}
  enable_inventory_management: {str(inventory).lower()}
  enable_reservation_mode: {str(is_reservation_mode).lower()}

# =============================
# CUSTOM NAMINGS
# =============================
custom_namings:
"""
    for k, v in namings.items():
        cfg += f"  {k}: \"{v}\"\n"

    cfg += f"""
# =============================
# Business Basics
# =============================
currency: "{data.get('currency', cat_defaults.get('currency', 'USD'))}"
tax_rate: {data.get('tax_rate', cat_defaults.get('tax_rate', 0.0))}
timezone: "{data.get('timezone', 'Asia/Singapore')}"

# =============================
# Business Hours
# =============================
business_hours:
{_format_hours_yaml(hours)}

# =============================
# Contact Information
# =============================
contact:
  address: "{data.get('address', '')}"
  phone: "{data.get('phone', '')}"
  email: "{data.get('email', '')}"
  website: "{data.get('website', '')}"

# =============================
# AI/Model Configuration
# =============================
model:
  path: "Elly0610/BotBrainv.4.1"
  confidence_threshold: 0.7
  max_response_length: 500

# =============================
# Storage
# =============================
storage:
  provider: "json"
  base_path: "data/"

# =============================
# Notifications
# =============================
notifications:
  telegram:
    bot_token: "${{NOTIFICATION_BOT_TOKEN}}"
"""

    if is_reservation_mode or booking:
        cfg += f"""
# =============================
# Booking / Reservation
# =============================
min_booking_notice: {data.get('min_booking_notice', 24)}
max_booking_lead_time: {data.get('max_booking_lead_days', 30)}

reservation:
  max_lead_time_days: 30
  min_notice_hours: 2
  confirmation_timeout_minutes: 15
  max_duration_hours: 4
  allow_off_hours: false
"""

    if ordering:
        cfg += f"""
# =============================
# Ordering
# =============================
ordering:
  currency: "{data.get('currency', cat_defaults.get('currency', 'USD'))}"
  tax_rate: {data.get('tax_rate', cat_defaults.get('tax_rate', 0.0))}
  min_order_amount: {data.get('min_order_amount', 0.0)}
  max_order_amount: {data.get('max_order_amount', 9999.99)}
"""


    product_source = data.get("product_source", "static")
    if product_source == "apps_script":
        apps_script_url = data.get("apps_script_url", "")
        cfg += f"""
# =============================
# Inventory Source
# =============================
inventory_source:
  type: "apps_script"
  apps_script_url: "{apps_script_url}"
  sync_interval_minutes: {data.get('sync_interval_minutes', 60)}
  last_sync: ""
  last_sync_status: "pending"
"""
    else:
        cfg += f"""
# =============================
# Inventory Source
# =============================
inventory_source:
  type: "static"
"""

    return cfg


def _build_namings(data: dict) -> dict[str, str]:
    """Build naming terms based on category and overrides."""
    cat_defaults = CATEGORY_DEFAULTS.get(data.get("category", "generic"), {})
    return {
        "order": data.get("order_term", cat_defaults.get("order_term", "Order")),
        "book": data.get("book_term", "Book"),
        "booking": data.get("booking_term", cat_defaults.get("booking_term", "Booking")),
        "product": data.get("product_term", cat_defaults.get("product_term", "Product")),
        "service": data.get("service_term", cat_defaults.get("service_term", "Service")),
        "menu": "Menu",
        "cart": data.get("cart_term", cat_defaults.get("cart_term", "Cart")),
        "reservation": data.get("booking_term", cat_defaults.get("booking_term", "Reservation")),
        "appointment": "Appointment",
    }


def _build_hours(data: dict, defaults: dict) -> dict:
    """Build business hours dict with defaults."""
    default_open = defaults.get("hours_open", "09:00")
    default_close = defaults.get("hours_close", "18:00")

    return {
        "monday": {
            "open": data.get("hours_monday_open", default_open),
            "close": data.get("hours_monday_close", default_close),
        },
        "tuesday": {
            "open": data.get("hours_tuesday_open", default_open),
            "close": data.get("hours_tuesday_close", default_close),
        },
        "wednesday": {
            "open": data.get("hours_wednesday_open", default_open),
            "close": data.get("hours_wednesday_close", default_close),
        },
        "thursday": {
            "open": data.get("hours_thursday_open", default_open),
            "close": data.get("hours_thursday_close", default_close),
        },
        "friday": {
            "open": data.get("hours_friday_open", default_open),
            "close": data.get("hours_friday_close", default_close),
        },
        "saturday": {
            "open": data.get("hours_saturday_open", "10:00"),
            "close": data.get("hours_saturday_close", "17:00"),
        },
        "sunday": {
            "open": data.get("hours_sunday_open", "00:00"),
            "close": data.get("hours_sunday_close", "00:00"),
        },
    }


def _format_hours_yaml(hours: dict) -> str:
    """Format hours dict as YAML string."""
    lines = []
    for day, times in hours.items():
        lines.append(f"  {day}:")
        lines.append(f"    - open: \"{times['open']}\"")
        lines.append(f"      close: \"{times['close']}\"")
    return "\n".join(lines)


def generate_responses(data: dict, use_llm: bool = True) -> str:
    """
    Generate comprehensive responses.yaml for the business.

    Uses LLM to generate personalized responses based on business category
    and description. Falls back to template-based generation if LLM unavailable.

    Args:
        data: Business data from onboarding form
        use_llm: Whether to attempt LLM generation (default True)
    """

    if use_llm and LLM_AVAILABLE and generate_responses_with_llm:
        try:
            return generate_responses_with_llm(data)
        except Exception as e:
            logger.warning(f"LLM response generation failed: {e}, using template fallback")


    return _generate_responses_template(data)


def generate_responses_template(data: dict) -> str:
    """Template-based response generation (original implementation)."""
    enabled = data.get("features", {})
    display_name = data.get("display_name", "Business")

    has_ordering = enabled.get("enable_ordering_system", False)
    has_booking = enabled.get("enable_booking_system", False)
    has_accounts = enabled.get("enable_customer_accounts", False)
    ordering_mode = "cart"
    if enabled.get("enable_reservation_mode", False):
        ordering_mode = "reservation"

    lines = [
        "# =============================",
        f"# {display_name} — Bot Responses",
        "# =============================",
        "# Auto-generated based on enabled features",
        "",
    ]


    lines += [
        "# =============================",
        "# Global / Fallback Responses",
        "# =============================",
        "",
        "intent_greeting: |",
        f'  Hi there! Welcome to **{display_name}**!',
        f"  Ready to get started?",
        "  Type **help** to see all available options.",
        "",
        "intent_goodbye: |",
        f'  Thank you for visiting {display_name}!',
        "  See you around!",
        "",
        "intent_fallback: |",
        "  **Let me help you get to the right place!**",
        "  ",
        "  I think you might be looking for:",
        "  ",
    ]

    if has_ordering:
        lines.append("  🛒 **ORDERING**")
        lines.append('  - "show products" or "buy"')
        lines.append('  - "what\'s in my cart?"')
        lines.append("  ")
    if has_booking:
        lines.append("  📅 **BOOKINGS**")
        lines.append('  - "make a booking"')
        lines.append('  - "view my bookings"')
        lines.append("  ")
    lines += [
        "  ℹ️ **INFO**",
        '  - "hours" or "open now?"',
        '  - "location" or "address"',
        '  - "contact"',
        "  ",
        "  💡 Type **help** for complete guide.",
        "",
        "intent_thanks: |",
        "  You're welcome! If you need anything else, just let me know.",
        "",
        "intent_help: |",
        f"  🆘 **{display_name} Help**",
        "  ",
        "  **I can help you with:**",
        "  ",
    ]

    if has_ordering:
        lines += [
            "  🛒 **ORDERING**",
            '  - `buy` or `show products` – Browse our products',
            '  - `view cart` – See what\'s in your cart',
            '  - `add [product]` – Add items to cart',
            '  - `edit cart` – Remove or change quantities',
            '  - `confirm order` – Finalize your purchase',
            "  ",
        ]
    if has_booking:
        lines += [
            "  📅 **BOOKING SYSTEM**",
            '  - `book` or `make booking` – Start a new booking',
            '  - `my bookings` – View your appointments',
            '  - `cancel booking` – Cancel an existing booking',
            "  ",
        ]
    lines += [
        "  ℹ️ **INFO**",
        '  - `hours` – Our opening hours',
        '  - `location` – Find our store',
        '  - `contact` – Get in touch',
        "  ",
        "  🔄 **SESSION CONTROL**",
        '  - `quit` or `exit` – End current flow',
        '  - `help` – Show this message again',
        "",
    ]


    lines += [
        "intent_business_hours: |",
        "  {is_open_now}",
        "  ",
        "  📅 **Our Business Hours:**",
        "  ",
        "  {{hours}}",
        "",
        "intent_location: |",
        "  📍 **Find Us:**",
        "  ",
        f"  **{display_name}**",
        "  ",
        "  {{address}}",
        "  ",
        "  {is_open_now}",
        "",
        "intent_contact: |",
        "  📞 **Contact Us:**",
        "  ",
        "  **Phone:** {{phone}}",
        "  **Email:** {{email}}",
        "  ",
        "  💬 Live Support: You're talking to me! I can help right now.",
        "",
    ]


    about_templates = {
        "bakery": [
            f"  🏆 **About {display_name}:**",
            "  ",
            f"  We're passionate about baking fresh, delicious treats every single day.",
            "  From our signature pastries to custom cakes, everything is made with love and the finest ingredients.",
            "  Can't wait to serve you!",
        ],
        "restaurant": [
            f"  🍽️ **About {display_name}:**",
            "  ",
            f"  We believe great food brings people together. Our kitchen crafts every dish with care, using fresh, local ingredients whenever possible.",
            f"  Thank you for choosing {display_name}!",
        ],
        "cafe": [
            f"  ☕ **About {display_name}:**",
            "  ",
            f"  More than just coffee — we're your neighborhood gathering spot. Whether it's a quick espresso or a leisurely brunch, we've got you covered.",
        ],
        "salon": [
            f"  💇 **About {display_name}:**",
            "  ",
            f"  Where style meets expertise. Our talented team stays on top of the latest trends to make sure you always leave looking and feeling your best.",
        ],
        "clinic": [
            f"  ⚕️ **About {display_name}:**",
            "  ",
            f"  Your health and comfort are our top priorities. Our experienced team is dedicated to providing compassionate, professional care in a welcoming environment.",
        ],
        "spa": [
            f"  🧘 **About {display_name}:**",
            "  ",
            f"  Escape the everyday and recharge with us. From relaxing treatments to revitalizing therapies, we're here to help you look and feel amazing.",
        ],
        None: [
            f"  🏆 **About {display_name}:**",
            "  ",
            f"  Thank you for your interest in {display_name}! We're dedicated to providing excellent service and a great experience for every customer.",
        ],
    }


    cat = data.get("category", "").lower()
    about_lines = about_templates[None]
    for cat_key in about_templates:
        if cat_key and cat_key in cat:
            about_lines = about_templates[cat_key]
            break

    lines += [
        "intent_about: |",
    ] + [f"  {line.strip()}" for line in about_lines] + ["", ""]


    if has_ordering and ordering_mode == "cart":
        lines += [
            "",
            "# =============================",
            "# Cart / Ordering (Full Cart Mode)",
            "# =============================",
            "",
            "cart_empty: |",
            "  🛒 Your cart is empty.",
            '  Type **buy** or **show products** to get started!',
            "",
            "no_products_available: |",
            "  Sorry, no products are available at the moment.",
            "  Please check back later!",
            "",
            "category_menu_prompt: |",
            "  🍽️ Please select a category:",
            "  {categories}",
            "  Type the **category name** or **number**.",
            "",
            "product_menu_prompt: |",
            "  🍰 Here are our products:",
            "  {menu}",
            "  Type the product **name** or **number** to add to cart.",
            "",
            "add_more_prompt: |",
            "  Would you like to add more items?",
            "  Reply **yes** or **no**",
            "",
            "cart_summary: |",
            "  🛒 **Your Cart:**",
            "  ",
            "  {summary}",
            "  ",
            "  You can confirm, cancel, or edit your cart.",
            '  Reply **confirm**, **cancel**, or **edit**.',
            "",
        ]
        lines += [
            "order_confirmed: |",
            "  ✅ **Order Confirmed!**",
            "  ",
            "  Thank you for your purchase!",
            "  ",
            "  Order ID: {order_id}",
            "  ",
            "order_canceled: |",
            "  ❌ **Order Canceled**",
            "  ",
            "  Your order has been cancelled.",
            "  ",
            "  Type **buy** to start a new order!",
            "",
            "edit_cart_prompt: |",
            "  ✏️ **Editing Cart:**",
            "  {items}",
            "  ",
            "  Examples:",
            '  - "remove 1" → remove by number',
            '  - "change 2 to 3" → update quantity',
            '  - "clear cart" → empty your cart',
            "",
            "item_not_found: |",
            "  ❌ I couldn't find that item in your cart.",
            "  Please check the number or name.",
            "",
            "item_removed: |",
            "  ✅ Removed **{item}**",
            "",
            "quantity_updated: |",
            "  ✅ Updated **{item}** quantity to **{qty}**",
            "",
            "cart_cleared: |",
            "  🧹 Cart cleared!",
            "  ",
            "  Type **buy** to add products.",
            "",
            "category_selection_fallback: |",
            "  ❌ I didn't recognize that category.",
            '  Please select from the menu or type its number.',
            "",
            "product_selection_fallback: |",
            "  ❌ I didn't recognize that product.",
            '  Please select from the menu or type its number.',
            "",
            "confirmation_fallback: |",
            '  Please reply **confirm**, **cancel**, or **edit**.',
            "",
            "empty_cart_confirmation: |",
            "  🛒 Your cart is empty — nothing to confirm.",
            "",
        ]


    if has_ordering and ordering_mode == "reservation":
        lines += [
            "",
            "# =============================",
            "# Reservation Mode (No Online Payment)",
            "# =============================",
            "",
            "cart_empty: |",
            "  🛒 Your cart is empty.",
            '  Type **buy** or **show products** to get started!',
            "",
            "no_products_available: |",
            "  Sorry, no products are available at the moment.",
            "",
            "category_menu_prompt: |",
            "  🍽️ Please select a category:",
            "  {categories}",
            "",
            "product_menu_prompt: |",
            "  🍰 Here are our products:",
            "  {menu}",
            "",
            "cart_summary_reservation: |",
            "  📋 **Reservation Summary:**",
            "  ",
            "  {summary}",
            "  ",
            '  Reply **yes** to confirm, **no** to cancel, or **edit** to modify.',
            "",
            "enter_reservation_datetime: |",
            "  📅 **Select Pickup Day**",
            "  ",
            "  • Type a number (1, 2, 3...) to select a day",
            '  • Type a day name (e.g., "tomorrow", "friday")',
            "",
            "day_selected_prompt: |",
            "  📅 **Selected:** {day_display}",
            "  ",
            "  **Business Hours:**",
            "  {business_hours}",
            "  ",
            '  Please enter your preferred time (e.g., "14:00" or "2pm")',
            "",
            "invalid_reservation_datetime: |",
            "  ❌ **Could not understand the date**",
            "  ",
            '  Please type a number (1, 2, 3...) or a day name (e.g., "tomorrow")',
            "",
            "reservation_datetime_invalid: |",
            "  ❌ {error_message}",
            "  ",
            "  **Business Hours:**",
            "  {business_hours}",
            "",
            "reservation_confirmed: |",
            "  ✅ **Reservation Confirmed!**",
            "  ",
            "  **Date & Time:** {datetime}",
            "  ",
            "  **Items:**",
            "  {summary}",
            "  ",
            "  Thank you! Please arrive on time. 💡 Payment will be collected on pickup.",
            "",
            "reservation_time_expired: |",
            "  ⏰ **Reservation Expired**",
            "  ",
            "  Your reservation was not confirmed in time and has been cancelled.",
            "  ",
            '  Type **buy** to make a new reservation.',
            "",
            "reservation_confirmed_with_time: |",
            "  ✅ **Reservation Confirmed!**",
            "  ",
            "  **Date & Time:** {datetime}",
            "  **Items:** {summary}",
            "  ",
            "  Please arrive on time. Your reservation will be held for {timeout} minutes.",
            "",
        ]


    if has_booking:
        lines += [
            "",
            "# =============================",
            "# Booking System Responses",
            "# =============================",
            "",
            "select_service_prompt: |",
            "  📅 **Let's book a service!**",
            "  ",
            "  Here's what we offer:",
            "  {menu}",
            "  ",
            "  Type the **number** or **service name** to select.",
            '  Type **cancel** to exit booking.',
            "",
            "invalid_service_selection: |",
            "  ❌ **Service not found**",
            "  ",
            '  Please choose from the list above.',
            "",
            "enter_party_size: |",
            "  👥 How many people are in your party?",
            "",
            "invalid_party_size: |",
            "  ❌ Please enter a valid number (e.g., 2, 4, 6).",
            "",
            "enter_topic: |",
            "  💬 Any notes or special requests?",
            "",
            "enter_datetime: |",
            "  📅 **Please enter your preferred date and time**",
            "  ",
            "  **Format:** YYYY-MM-DD HH:MM",
            '  **Example:** 2024-01-15 14:30',
            "",
            "invalid_time_format: |",
            "  ❌ **Invalid time format**",
            "  ",
            "  Please use: **YYYY-MM-DD HH:MM**",
            '  **Example:** 2024-01-15 14:30',
            "",
            "past_date_error: |",
            "  ❌ Please choose a **future** date and time.",
            "  You cannot book in the past.",
            "",
            "business_hours_closed_day: |",
            "  ❌ **We're closed on {day_name}**",
            "  ",
            "  **Our business hours are:**",
            "  {business_hours}",
            "  ",
            "  Please choose another day.",
            "",
            "business_hours_outside_hours: |",
            "  ❌ **That time is outside our business hours**",
            "  ",
            "  **Our business hours are:**",
            "  {business_hours}",
            "",
            "enter_name: |",
            "  👤 Please enter your name:",
            "",
            "enter_special_requests: |",
            "  💫 **Any special requests?**",
            "  ",
            "  - Dietary restrictions",
            "  - Accessibility needs",
            "  - Special occasions",
            "  ",
            '  Type **none** or **skip** if no requests.',
            "",
            "confirm_booking_prompt: |",
            "  ✅ **Please confirm your booking:**",
            "  ",
            "  **Service:** {service_name}",
            "  **Date & Time:** {datetime}",
            "  **Name:** {customer_name}",
            "  **Party Size:** {party_size}",
            "  {special_requests_line}",
            "  ",
            '  Reply **yes** to confirm or **no** to cancel.',
            "",
            "booking_confirmed: |",
            "  ✅ **Booking Confirmed!**",
            "  ",
            "  **Service:** {service_name}",
            "  **Date & Time:** {datetime}",
            "  **Party Size:** {party_size}",
            "  ",
            "  Thank you! We're looking forward to serving you.",
            "",
            "booking_canceled: |",
            "  ✅ Your booking has been canceled.",
            "  ",
            '  Type **book** to create a new booking!',
            "",
            "slot_locked: |",
            "  ❌ Sorry, that time slot is no longer available.",
            "  Please choose another time.",
            "",
            "no_services_available: |",
            "  ❌ No booking services are available at the moment.",
            "",
            "booking_help: |",
            "  💡 **Booking Help**",
            "  ",
            "  **During booking, you can:**",
            '  - Type **back** to go to previous step',
            '  - Type **cancel** to exit',
            '  - Type **help** for this message',
            "",
        ]
        lines += [
            "",
            "# =============================",
            "# Booking Management",
            "# =============================",
            "",
            "bookings_list: |",
            "  📅 **Your Bookings:**",
            "  ",
            "  {bookings_list}",
            "  ",
            '  Type **cancel booking** + ID to cancel.',
            '  Type **book** to make a new booking.',
            "",
            "bookings_list_empty: |",
            "  📅 **No Active Bookings**",
            "  ",
            "  You don't have any upcoming bookings.",
            '  Type **book** to create one!',
            "",
            "cancellation_prompt: |",
            "  📅 **Your Bookings:**",
            "  ",
            "  {bookings_list}",
            "  ",
            '  Reply with the booking ID (e.g., `abc12345`)',
            '  Or type **cancel** to exit.',
            "",
            "confirm_cancellation: |",
            "  ⚠️ **Confirm Cancellation**",
            "  ",
            "  **Service:** {service_name}",
            "  **Date & Time:** {datetime}",
            "  **Booking ID:** {booking_id}",
            "  ",
            '  Reply **yes** to confirm or **no** to keep.',
            "",
            "cancellation_successful: |",
            "  ✅ **Booking Cancelled**",
            "  ",
            "  Your booking has been cancelled.",
            "  We hope to serve you another time!",
            "",
            "cancellation_error: |",
            "  ❌ **Cancellation Error**",
            "  ",
            "  There was an error. Please try again.",
            "",
            "no_bookings_found: |",
            "  📅 **No Bookings Found**",
            "  ",
            '  Type **book** to create a new booking!',
            "",
            "booking_not_found: |",
            "  ❌ **Booking Not Found**",
            "  ",
            "  Please check the booking ID and try again.",
            "",
        ]
        lines += [
            "",
            "# =============================",
            "# Booking Flow Fallbacks",
            "# =============================",
            "",
            "fallback_service_selection: |",
            "  🤔 I didn't understand your selection.",
            "  ",
            "  💡 Try: Type a **number** (1, 2...) or the **service name**.",
            '  Type **cancel** to exit booking.',
            "",
            "fallback_party_size: |",
            "  🤔 I need to know your party size.",
            "  ",
            '  Please enter a number (e.g., "2", "4")',
            "",
            "fallback_datetime_selection: |",
            "  🤔 I need your preferred date and time.",
            "  ",
            '  Use format: **YYYY-MM-DD HH:MM**',
            "",
            "fallback_name_collection: |",
            "  🤔 I need your name for the booking.",
            "  ",
            '  Please enter your full name.',
            "",
            "fallback_confirmation: |",
            "  🤔 Ready to confirm?",
            "  ",
            '  Reply **yes** or **confirm** to book.',
            '  Reply **no** to cancel.',
            "",
            "general_fallback: |",
            "  🤔 I'm not sure what you'd like to do.",
            "  ",
            '  Type **help** for guidance.',
            '  Type **cancel** to exit.',
            "",
        ]


    if has_accounts:
        lines += [
            "",
            "# =============================",
            "# Customer Account Responses",
            "# =============================",
            "",
            "account_login: |",
            "  👤 **Login to Your Account**",
            "  ",
            "  Please enter your email and password.",
            "",
            "account_created: |",
            "  ✅ **Account Created!**",
            "  ",
            "  Welcome to {business_name}!",
            "",
            "account_logout: |",
            "  👋 You've been logged out.",
            "  See you again!",
            "",
            "account_view_orders: |",
            "  📦 **Your Order History:**",
            "  ",
            "  {order_list}",
            "",
            "account_profile: |",
            "  👤 **Your Profile:**",
            "  ",
            "  **Name:** {name}",
            "  **Email:** {email}",
            "",
            "account_no_orders: |",
            "  📦 You haven't placed any orders yet.",
            '  Type **buy** to get started!',
            "",
        ]


    lines += [
        "",
        "# =============================",
        "# Global Error Handling",
        "# =============================",
        "",
        "error_fallback: |",
        "  ⚠️ Something went wrong.",
        '  Type **help** or try again.',
        "",
        "current_state_fallback: |",
        "  How can I help with your order?",
        '  Type **help** for options.',
        "",
        "quit_prompt: |",
        "  Are you sure you want to cancel?",
        '  Reply **yes** or **no**.',
        "",
        "quit_continue: |",
        "  Okay, continuing...",
        "",
        "unexpected_input: |",
        "  🤔 I didn't quite understand that.",
        "  ",
        "  {current_step_instruction}",
        '  Type **help** for guidance.',
        "",
    ]

    return "\n".join(lines)


def generate_preview(data: dict, use_llm: bool = True) -> dict[str, str]:
    """Generate all config files for preview."""
    f = data.get("features", {})
    files = {
        "business_config.yaml": generate_business_config(data),
        "responses.yaml": generate_responses(data, use_llm=use_llm),
    }

    if f.get("ordering") and data.get("product_source", "static") != "apps_script":
        files["products.json"] = generate_products_json(data)

    if f.get("booking") or (f.get("ordering") and f.get("ordering_mode") == "reservation"):
        files["services.yaml"] = generate_services_yaml(data)

    return files
def generate_products_json(data: dict) -> str:
    """Generate products.json for ordering businesses.

    Outputs a plain JSON array matching the format ProductHandler expects
    and SheetSyncManager produces — flat list of product dicts.
    """
    cat_defaults = CATEGORY_DEFAULTS.get(data.get("category", "generic"), {})
    product_term = data.get("product_term", cat_defaults.get("product_term", "Product"))

    return json.dumps([
        {
            "name": f"Sample {product_term} 1",
            "description": "A delicious sample item.",
            "price": 9.99,
            "category": "Category 1",
            "available": True,
            "bookable": False,
            "max_quantity": 99,
        },
        {
            "name": f"Sample {product_term} 2",
            "description": "Another great choice.",
            "price": 14.99,
            "category": "Category 1",
            "available": True,
            "bookable": False,
            "max_quantity": 99,
        },
        {
            "name": f"Sample {product_term} 3",
            "description": "A premium option.",
            "price": 24.99,
            "category": "Category 2",
            "available": True,
            "bookable": False,
            "max_quantity": 99,
        },
    ], indent=2)


def generate_services_yaml(data: dict) -> str:
    """Generate services.yaml for booking businesses."""
    cat_defaults = CATEGORY_DEFAULTS.get(data.get("category", "generic"), {})
    booking_term = data.get("booking_term", cat_defaults.get("booking_term", "service"))
    service_term = data.get("service_term", cat_defaults.get("service_term", "Service"))

    return f"""# =============================
# {data['display_name']} — Services
# =============================
# Available {service_term.lower()}s for booking/reservation

services:
  - id: "svc_1"
    name: "{service_term} 1"
    description: "A sample {service_term.lower()}."
    duration_minutes: 60
    price: 50.00
    capacity: 1
    available: true

  - id: "svc_2"
    name: "{service_term} 2"
    description: "Another available {service_term.lower()}."
    duration_minutes: 90
    price: 80.00
    capacity: 1
    available: true

  - id: "svc_3"
    name: "{service_term} 3"
    description: "A premium {service_term.lower()}."
    duration_minutes: 120
    price: 120.00
    capacity: 1
    available: true

# Service categories
categories:
  - id: "cat_svc_1"
    name: "Standard"
    description: "Standard {service_term.lower()}s"
  - id: "cat_svc_2"
    name: "Premium"
    description: "Premium {service_term.lower()}s"
"""
