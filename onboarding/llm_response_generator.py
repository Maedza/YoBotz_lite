"""
LLM-powered response generator for business onboarding.
Uses AI to generate customized bot responses based on business category and description.
"""

import os
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


class ResponseContext:
    """Context data for generating business-specific responses."""
    def __init__(
        self,
        business_name: str,
        business_category: str,
        business_description: str,
        features: dict[str, Any],
    ):
        self.business_name = business_name
        self.business_category = business_category
        self.business_description = business_description
        self.features = features


def _get_tone_instructions(category: str) -> str:
    """Return category-specific tone guidance for the LLM."""
    tones = {
        "bakery": "Warm, cozy, inviting. Use words like 'fresh', 'baked', 'treats', 'artisanal'. Feel like a friendly neighborhood bakery.",
        "restaurant": "Appetizing, welcoming, enthusiastic about food. Use sensory language. Feel like a favorite local spot.",
        "cafe": "Relaxed, cozy, friendly. Casual vibe. Feel like your regular coffee place.",
        "salon": "Trendy, confident, pampering. Use words like 'style', 'look', 'refreshed'. Feel like a chic boutique salon.",
        "clinic": "Professional, reassuring, trustworthy. Calm and clear. No medical jargon. Make patients feel safe.",
        "spa": "Tranquil, luxurious, relaxing. Use soothing words. Feel like an escape from daily stress.",
        "retail": "Energetic, helpful, exciting about products. Customer-focused. Feel like a trusted shop assistant.",
        "fitness": "Motivating, energetic, supportive. Encouraging but not pushy. Feel like a personal coach.",
        "generic": "Friendly, professional, helpful. Clear and approachable. A solid small business voice.",
    }

    cat_lower = category.lower()
    for key in tones:
        if key in cat_lower or cat_lower in key:
            return tones[key]
    return tones["generic"]


def build_llm_prompt(ctx: ResponseContext) -> str:
    """Build the prompt for LLM to generate customized responses."""

    category = ctx.business_category
    description = ctx.business_description
    name = ctx.business_name
    features = ctx.features


    has_ordering = features.get("enable_ordering_system", False)
    has_booking = features.get("enable_booking_system", False)
    has_accounts = features.get("enable_customer_accounts", False)
    ordering_mode = "cart"
    if features.get("enable_reservation_mode", False):
        ordering_mode = "reservation"


    feature_list: list[str] = []
    if has_ordering and ordering_mode == "cart":
        feature_list.append("- Ordering system with cart/checkout flow")
    elif has_ordering and ordering_mode == "reservation":
        feature_list.append("- Ordering system with reservation/pickup flow")
    if has_booking:
        feature_list.append("- Booking/appointment system")
    if has_accounts:
        feature_list.append("- Customer accounts")

    features_str = "\n".join(f"  {line}" for line in feature_list) if feature_list else "  - No specific features enabled"

    tone_guide = _get_tone_instructions(category)


    response_map = _build_response_map(features)


    response_requests: list[tuple[str, str]] = []
    for entry in response_map:
        marker = entry["marker"]
        desc = entry["desc"]

        if desc == "GREETING":
            body = "A warm welcome message when user starts a conversation. Mention the business name using {business_name} placeholder. (2-3 sentences)"
        elif desc == "GOODBYE":
            body = "A friendly farewell when user says goodbye. Keep brief and inviting. (1-2 sentences)"
        elif desc == "FALLBACK":
            body = "When bot doesn't understand input. Guide to available actions based on enabled features. (6-10 lines)"
        elif desc == "THANKS":
            body = "Simple acknowledgment when user says thanks. (1 sentence, warm but brief)"
        elif desc == "HELP":
            body = "Comprehensive help showing ALL available commands. Must include actual commands like `buy`, `hours`, `quit`. Be thorough. (12-18 lines)"
        elif desc == "HOURS":
            body = "Business hours. MUST use exactly {{hours}} on its own line. Do NOT invent hours. (3-5 lines)"
        elif desc == "LOCATION":
            body = "Address/directions. MUST use exactly {{address}} on its own line. Do NOT invent an address. (3-4 lines)"
        elif desc == "CONTACT":
            body = "Phone/email. MUST use exactly {{phone}} and {{email}} placeholders. Do NOT invent contact info. (3-4 lines)"
        elif desc == "ABOUT":
            body = "Brief about us. Match business description. What makes them special. (4-7 lines)"
        elif desc == "CART_EMPTY":
            body = "Friendly message when cart is empty, encourage browsing. (1-2 sentences)"
        elif desc == "CART_SUMMARY":
            body = "Cart review showing items with next-step instructions. Uses {{summary}}. (3-4 lines)"
        elif desc == "ORDER_CONFIRMED":
            body = "Celebration after order. Warm, includes {{order_id}}. (2-3 sentences)"
        elif desc == "ORDER_CANCELLED":
            body = "Brief cancellation confirmation. (1 sentence)"
        elif desc == "RESERVATION_SUMMARY":
            body = "Summary of reservation before confirmation. Uses {{summary}}. (3-4 lines)"
        elif desc == "PICKUP_PROMPT":
            body = "Ask customer to select pickup date/time. (2-3 lines)"
        elif desc == "RESERVATION_CONFIRMED":
            body = "Confirmation with pickup details. Uses {{datetime}}, {{summary}}. (3-4 lines)"
        elif desc == "SELECT_SERVICE":
            body = "Prompt to choose from available services. Uses {{menu}}. (3-4 lines)"
        elif desc == "BOOKING_CONFIRMED":
            body = "Celebration after booking. Uses {{service_name}}, {{datetime}}, {{party_size}}. (3-4 lines)"
        elif desc == "BOOKING_CANCELLED":
            body = "Brief cancellation confirmation. (1 sentence)"
        elif desc == "MY_BOOKINGS":
            body = "List bookings. Uses {{bookings_list}}. Include cancel instructions. (4-6 lines)"
        elif desc == "LOGIN_PROMPT":
            body = "Ask user to login. (1-2 sentences)"
        elif desc == "ACCOUNT_CREATED":
            body = "Welcome new user after registration. (2-3 sentences)"
        elif desc == "ORDER_HISTORY":
            body = "Show past orders summary. (3-4 lines)"
        else:
            body = "Response content. (2-3 lines)"

        response_requests.append((f"{marker}: {desc}", body))

    responses_section = "\n".join(f"  {label} - {desc}" for label, desc in response_requests)
    num_responses = len(response_requests)

    placeholder_rules = ""
    if any(e["desc"] == "HOURS" for e in response_map):
        placeholder_rules += "- {{hours}} marker (RESPONSE_06): MUST include exactly {{hours}} on its own line. Do NOT write times.\n  CORRECT: \"Our hours:\n\n{{hours}}\"\n  WRONG: \"We are open Mon-Fri 9am-5pm\"\n"
    if any(e["desc"] == "LOCATION" for e in response_map):
        placeholder_rules += "- {{address}} marker (RESPONSE_07): MUST include exactly {{address}} on its own line. Do NOT write street addresses.\n  CORRECT: \"Find us here:\n\n{{address}}\"\n  WRONG: \"We are at 123 Main Street\"\n"
    if any(e["desc"] == "CONTACT" for e in response_map):
        placeholder_rules += "- {{phone}}/{{email}} markers (RESPONSE_08): MUST use placeholders exactly. Do NOT invent contact info.\n  CORRECT: \"Reach us:\nPhone: {{phone}}\nEmail: {{email}}\"\n  WRONG: \"Call us at 555-123-4567\"\n"
    if any(e["desc"] == "HELP" for e in response_map):
        placeholder_rules += "- RESPONSE_05 (HELP): Must be LONG and COMPREHENSIVE. Cover ALL enabled features."

    prompt = f"""You are a professional copywriter creating responses for a **{name}** Telegram chatbot.

BUSINESS CONTEXT:
- Category: {category}
- Description: {description}
- Features enabled:
{features_str}

TONE GUIDE: {tone_guide}

TASK:
Generate natural, engaging bot responses. You will produce EXACTLY {num_responses} responses.

RESPONSES TO GENERATE:

{responses_section}

=== OUTPUT RULES (FOLLOW EXACTLY — ORDER MATTERS!) ===

1. Write EXACTLY {num_responses} responses IN THE SAME ORDER as listed above
2. Each response MUST start with its assigned marker (e.g. "RESPONSE_01: ", "RESPONSE_02: ")
3. Do NOT change, skip, or reorder markers — output them sequentially from 01 to {num_responses:02d}
4. The marker is the ONLY prefix allowed — no dashes, no bold labels before content
5. Use {{business_name}} for the business name (NOT the actual name)
6. Use **bold** for emphasis (Telegram markdown compatible)
7. Use emojis sparingly and naturally (max 1-2 per response)
8. Blank lines between responses are OK

=== PLACEHOLDER RULES (CRITICAL - VIOLATION CAUSES FAILURE) ===

{placeholder_rules}

=== ANTI-PATTERNS (NEVER DO THESE) ===

- NEVER write fake addresses like "123 Main Street" or "Bakery District"
- NEVER write fake phone numbers like "(555) 123-4567"
- NEVER write fake emails like "hello@business.com"
- NEVER write specific business hours — always use {{hours}}
- NEVER make up facts not in the business description
- NEVER leave a response blank or nearly blank (minimum 2 meaningful lines)
- NEVER skip a response number

=== EXAMPLE OF CORRECT OUTPUT FORMAT ===

RESPONSE_01: Hi there! Welcome to **{{business_name}}**! I'm here to help you find what you need. Just let me know how I can assist you today!

RESPONSE_02: Thanks for choosing **{{business_name}}**! We appreciate you. Come back anytime!

RESPONSE_03: I'm not sure what you need. Here's what I can help with:

**Ordering**
- Type `buy` or `show products` to browse
- Type `view cart` to see your cart

**Info**
- Type `hours` for opening times
- Type `location` for our address

[... continue with ALL {num_responses} responses in exact number order ...]

---

Now generate all {num_responses} responses IN ORDER, starting each with its marker. Do NOT skip any numbers or change the order:"""

    return prompt


def call_llm(prompt: str, model: Optional[str] = None) -> Optional[str]:
    """
    Call LLM API to generate responses.
    Falls back to template responses if LLM unavailable.
    """

    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            import openai
            client = openai.OpenAI(
                api_key=groq_key,
                base_url="https://api.groq.com/openai/v1"
            )

            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "You are a helpful copywriter."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2048,
                temperature=0.7,
            )

            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"Groq API failed: {e}")


    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful copywriter."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2048,
                temperature=0.7,
            )

            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"OpenAI API failed: {e}")


    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        try:
            import openai
            client = openai.OpenAI(
                api_key=openrouter_key,
                base_url="https://openrouter.ai/api/v1"
            )

            response = client.chat.completions.create(
                model="meta-llama/llama-3.1-8b-instruct",
                messages=[
                    {"role": "system", "content": "You are a helpful copywriter."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2048,
                temperature=0.7,
            )

            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"OpenRouter API failed: {e}")


    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)

            response = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}]
            )

            return response.content[0].text
        except Exception as e:
            logger.warning(f"Anthropic API failed: {e}")

    return None


import re


_STRIP_PREFIXES = re.compile(
    r'^(?:'
    r'\*\*\d+[\.\)]\s+\w.*?\*\*[\s:]*'
    r'|\d+[\.\)]\s+'
    r'|\*\*[\w\s]+:\*\*\s*'
    r'|-\s*'
    r')',
    re.IGNORECASE
)


def parse_llm_output(output: str, response_map: Optional[list[dict[str, str]]] = None) -> list[str]:
    """Parse LLM output into individual responses.

    Strategy:
    1. Extract by RESPONSE_NN: prefix markers (new format)
    2. Verify label matches response_map at each position (alignment check)
    3. Fall back to blank-line splitting if labels misaligned or markers missing

    Returns ordered list of response body texts (no markers).
    """

    marker_pattern = re.compile(r'^RESPONSE_(\d+):\s*', re.IGNORECASE)
    lines = output.split("\n")

    numbered_responses: dict[int, str] = {}

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        match = marker_pattern.match(stripped)
        if match:
            num = int(match.group(1))
            body = stripped[match.end():]

            body_lines = [body] if body else []
            for j in range(i + 1, len(lines)):
                next_line = lines[j].strip()
                if marker_pattern.match(next_line):
                    break
                if not next_line:
                    if body_lines:
                        break
                    continue
                body_lines.append(next_line)

            numbered_responses[num] = "\n".join(body_lines).strip()

    if numbered_responses:
        max_num = max(numbered_responses.keys())
        min_needed = 3 if not response_map else max(3, len(response_map) - 2)

        if len(numbered_responses) >= min_needed:

            if response_map:
                expected_sequence = [e["marker"] for e in response_map]
                actual_sequence = sorted(numbered_responses.keys())


                alignment_ok = True

                for idx, entry in enumerate(response_map[:3]):
                    expected_marker = entry["marker"]
                    if actual_sequence and idx < len(actual_sequence):
                        actual_marker_num = actual_sequence[idx]
                        expected_num = int(expected_marker.split("_")[1])
                        if actual_marker_num != expected_num:
                            alignment_ok = False
                            break

                if not alignment_ok:
                    logger.warning("LLM output marker sequence misaligned with response_map — using blank-line fallback")
                else:
                    logger.info(f"Parsed {len(numbered_responses)} numbered responses (max #{max_num}), alignment verified")


            ordered = []
            for n in range(1, max_num + 1):
                ordered.append(numbered_responses.get(n, ""))
            return ordered


    logger.warning("Using blank-line fallback for response parsing")
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue
        stripped = _STRIP_PREFIXES.sub('', stripped).strip()
        if stripped:
            cleaned_lines.append(stripped)

    responses: list[str] = []
    current: list[str] = []
    prev_empty = False

    for line in cleaned_lines:
        if not line:
            prev_empty = True
            continue
        if prev_empty and current:
            responses.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
        prev_empty = False

    if current:
        responses.append("\n".join(current))

    return responses


_SAFE_DEFAULTS = {
    "intent_greeting": (
        f"Hi there! Welcome to **{{business_name}}**! "
        "How can I help you today? Type **help** to see what I can do."
    ),
    "intent_goodbye": "Thank you for visiting **{business_name}**! Hope to see you again soon!",
    "intent_fallback": (
        "**I am not sure what you need.** Here is how I can help:\n\n"
        "**Ordering & Products**\n"
        "- buy or show products - Browse items\n\n"
        "**Business Info**\n"
        "- hours - Opening times\n"
        "- location - Find us\n"
        "- contact - Phone and email\n\n"
        "Type **help** for all commands."
    ),
    "intent_thanks": "You are welcome! Let me know if you need anything else.",
    "intent_help": (
        f"**{{business_name}} Help Center**\n\n"
        "**What I can help with:**\n\n"
        "**Ordering & Products**\n"
        "- buy or show products - Browse and order\n"
        "- view cart - See your cart\n\n"
        "**Bookings**\n"
        "- book or make appointment - Schedule one\n"
        "- my bookings - View upcoming\n\n"
        "**Info**\n"
        "- hours - Our opening hours\n"
        "- location - Find our store\n"
        "- contact - Phone and email\n"
        "- about - Learn about us\n\n"
        "**Control**\n"
        "- quit or exit - End current flow\n"
        "- help - Show this message\n\n"
        "Just ask naturally - I am here to help!"
    ),
    "intent_business_hours": "{is_open_now}\n\n📅 **Business Hours:**\n\n{{hours}}",
    "intent_location": "📍 **Find Us:**\n\n{{address}}\n\n{is_open_now}",
    "intent_contact": "📞 **Contact Us:**\n\n**Phone:** {{phone}}\n**Email:** {{email}}",
    "intent_about": f"About **{{business_name}}**:\n\nWe are dedicated to providing great service. Thank you for your interest!",
}

def _normalize_placeholders(text: str) -> str:
    """Normalize whitespace and single-brace variants to clean {{key}} format."""
    import re
    for key in ("hours", "address", "phone", "email", "business_name"):

        text = re.sub(r'\{\{\s*' + re.escape(key) + r'\s*\}\}', '{{' + key + '}}', text)

        text = re.sub(r'(?<!\{)\{' + re.escape(key) + r'\}(?!\})', '{{' + key + '}}', text)
    return text


def validate_and_fix_placeholders(responses: list[str], response_map: list[dict[str, str]]) -> list[str]:
    """
    Ensure ALL critical responses have correct placeholders, sufficient length,
    and no hardcoded data. Replace any failing response with a safe default.
    """
    import re

    fixed_responses = list(responses)


    _MIN: dict[str, tuple[int, str]] = {
        "intent_greeting":       (30,  "Greeting"),
        "intent_goodbye":        (10,  "Goodbye"),
        "intent_fallback":       (80,  "Fallback"),
        "intent_thanks":         (5,   "Thanks"),
        "intent_help":           (120, "Help"),
        "intent_business_hours": (15,  "Hours"),
        "intent_location":       (15,  "Location"),
        "intent_contact":        (15,  "Contact"),
        "intent_about":          (50,  "About"),
    }

    for idx in range(min(len(fixed_responses), len(response_map))):
        key = response_map[idx]["key"]
        response = fixed_responses[idx]
        clean_len = len(response.strip())


        if key in _MIN:
            min_len, label = _MIN[key]
            if clean_len < min_len:
                logger.warning(f"{label} too short ({clean_len}/{min_len} chars) - replacing with default")
                fixed_responses[idx] = _SAFE_DEFAULTS.get(key, response)
                continue


        response = _normalize_placeholders(response)

        if key == "intent_business_hours":
            if "{{hours}}" not in response:
                logger.warning("HOURS missing {{hours}} - fixing")
                response = re.sub(
                    r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s*[-–—to]+\s*\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?',
                    '{{hours}}', response, flags=re.IGNORECASE
                )
                if "{{hours}}" not in response:
                    response += "\n\n{{hours}}"
                fixed_responses[idx] = response

        elif key == "intent_location":
            if "{{address}}" not in response:
                logger.warning("LOCATION missing {{address}} - fixing")
                response = re.sub(
                    r'\b\d+\s+[A-Z][a-z]+\s+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Blvd|Boulevard|Way|Place|Pl)\b.*',
                    '{{address}}', response, flags=re.I
                )
                if "{{address}}" not in response:
                    response += "\n\n{{address}}"
                fixed_responses[idx] = response

        elif key == "intent_contact":

            normalized = response
            normalized = _normalize_placeholders(normalized)

            has_phone = "{{phone}}" in normalized
            has_email = "{{email}}" in normalized

            if not has_phone:
                normalized += "\n**Phone:** {{phone}}"
            if not has_email:
                normalized += "\n**Email:** {{email}}"


            lines = normalized.split("\n")
            seen, deduped = set(), []
            for line in lines:
                if line.strip() and line.strip() not in seen:
                    seen.add(line.strip())
                    deduped.append(line)

            fixed_responses[idx] = "\n".join(deduped)

    return fixed_responses


def format_as_yaml(responses: list[str], enabled: dict[str, Any], response_map: Optional[list[dict[str, str]]] = None) -> str:
    """Format parsed responses as YAML with proper keys."""
    lines: list[str] = [
        "# =============================",
        "# Bot Responses - LLM Generated",
        "# =============================",
        "# Auto-generated based on business category and description",
        "#",
        "# PLACEHOLDERS: The following placeholders are auto-replaced at runtime:",
        "#   {{hours}}   -> Formatted business hours from business_config.yaml",
        "#   {{address}} -> Business address from business_config.yaml",
        "#   {{phone}}   -> Business phone from business_config.yaml",
        "#   {{email}}   -> Business email from business_config.yaml",
        "",
    ]


    if response_map is None:
        response_map = _build_response_map(enabled)

    for i, response_text in enumerate(responses):
        if i < len(response_map):
            key = response_map[i]["key"]
            lines.append(f"{key}: |")
            for line in response_text.split("\n"):
                lines.append(f"  {line}")
            lines.append("")

    return "\n".join(lines)


def _build_response_map(enabled: dict[str, Any]) -> list[dict[str, str]]:
    """Build ordered list of response keys based on enabled features."""
    responses: list[dict[str, str]] = []


    has_ordering = enabled.get("enable_ordering_system", False)
    has_booking = enabled.get("enable_booking_system", False)
    has_accounts = enabled.get("enable_customer_accounts", False)
    ordering_mode = "cart"
    if enabled.get("enable_reservation_mode", False):
        ordering_mode = "reservation"


    responses.extend([
        {"key": "intent_greeting", "desc": "GREETING", "marker": "RESPONSE_01"},
        {"key": "intent_goodbye", "desc": "GOODBYE", "marker": "RESPONSE_02"},
        {"key": "intent_fallback", "desc": "FALLBACK", "marker": "RESPONSE_03"},
        {"key": "intent_thanks", "desc": "THANKS", "marker": "RESPONSE_04"},
        {"key": "intent_help", "desc": "HELP", "marker": "RESPONSE_05"},
        {"key": "intent_business_hours", "desc": "HOURS", "marker": "RESPONSE_06"},
        {"key": "intent_location", "desc": "LOCATION", "marker": "RESPONSE_07"},
        {"key": "intent_contact", "desc": "CONTACT", "marker": "RESPONSE_08"},
        {"key": "intent_about", "desc": "ABOUT", "marker": "RESPONSE_09"},
    ])

    idx = 10


    if has_ordering and ordering_mode == "cart":
        responses.extend([
            {"key": "cart_empty", "desc": "CART_EMPTY", "marker": f"RESPONSE_{idx:02d}"},
            {"key": "cart_summary", "desc": "CART_SUMMARY", "marker": f"RESPONSE_{idx+1:02d}"},
            {"key": "order_confirmed", "desc": "ORDER_CONFIRMED", "marker": f"RESPONSE_{idx+2:02d}"},
            {"key": "order_canceled", "desc": "ORDER_CANCELLED", "marker": f"RESPONSE_{idx+3:02d}"},
        ])
        idx += 4


    if has_ordering and ordering_mode == "reservation":
        responses.extend([
            {"key": "cart_empty", "desc": "RESERVATION_EMPTY", "marker": f"RESPONSE_{idx:02d}"},
            {"key": "cart_summary_reservation", "desc": "RESERVATION_SUMMARY", "marker": f"RESPONSE_{idx+1:02d}"},
            {"key": "enter_reservation_datetime", "desc": "PICKUP_PROMPT", "marker": f"RESPONSE_{idx+2:02d}"},
            {"key": "reservation_confirmed", "desc": "RESERVATION_CONFIRMED", "marker": f"RESPONSE_{idx+3:02d}"},
        ])
        idx += 4


    if has_booking:
        responses.extend([
            {"key": "select_service_prompt", "desc": "SELECT_SERVICE", "marker": f"RESPONSE_{idx:02d}"},
            {"key": "booking_confirmed", "desc": "BOOKING_CONFIRMED", "marker": f"RESPONSE_{idx+1:02d}"},
            {"key": "booking_canceled", "desc": "BOOKING_CANCELLED", "marker": f"RESPONSE_{idx+2:02d}"},
            {"key": "bookings_list", "desc": "MY_BOOKINGS", "marker": f"RESPONSE_{idx+3:02d}"},
        ])
        idx += 4


    if has_accounts:
        responses.extend([
            {"key": "account_login", "desc": "LOGIN_PROMPT", "marker": f"RESPONSE_{idx:02d}"},
            {"key": "account_created", "desc": "ACCOUNT_CREATED", "marker": f"RESPONSE_{idx+1:02d}"},
            {"key": "account_view_orders", "desc": "ORDER_HISTORY", "marker": f"RESPONSE_{idx+2:02d}"},
        ])

    return responses


def quality_gate_yaml(yaml_str: str, expected_map: list[dict[str, str]]) -> str:
    """
    Post-generation quality gate: validates YAML structure, ensures all keys exist,
    checks minimum content length, replaces any failing key with safe default.

    Returns guaranteed-valid YAML string.
    """
    import yaml

    lines = yaml_str.split("\n")


    try:
        parsed = yaml.safe_load(yaml_str) or {}
    except Exception as e:
        logger.warning(f"Quality gate: YAML parse failed ({e}), rebuilding from scratch")
        return None

    if not isinstance(parsed, dict):
        logger.warning("Quality gate: YAML root is not a dict, rebuilding")
        return None


    _MIN_LEN: dict[str, int] = {
        "intent_greeting":       30,
        "intent_goodbye":        10,
        "intent_fallback":       80,
        "intent_thanks":          5,
        "intent_help":          120,
        "intent_business_hours": 15,
        "intent_location":       15,
        "intent_contact":        15,
        "intent_about":          50,
    }

    failing_keys: list[str] = []

    for entry in expected_map:
        key = entry["key"]
        if key not in parsed:
            failing_keys.append(key)
            continue

        value = parsed[key]
        if isinstance(value, str):
            content = value.strip()
        elif isinstance(value, list):
            content = " ".join(str(v).strip() for v in value if str(v).strip())
        else:
            content = str(value).strip() if value else ""

        min_len = _MIN_LEN.get(key, 0)
        if min_len > 0 and len(content) < min_len:
            logger.warning(f"Quality gate: '{key}' too short ({len(content)}/{min_len} chars) - flagging")
            failing_keys.append(key)

    if not failing_keys:
        return yaml_str


    logger.info(f"Quality gate: Fixing {len(failing_keys)} failing key(s)")

    for key in failing_keys:
        default_val = _SAFE_DEFAULTS.get(key, f"[{key} response]")
        parsed[key] = default_val
        logger.info(f"Quality gate: Replaced '{key}' with safe default")

    fixed_yaml = yaml.dump(parsed, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return fixed_yaml


def generate_responses_with_llm(data: dict[str, Any], use_llm: bool = True) -> str:
    """
    Generate responses using LLM if available, fallback to templates.

    Args:
        data: Business data from onboarding form
        use_llm: Whether to attempt LLM generation (set False for fallback)

    Returns:
        YAML-formatted responses string
    """
    ctx = ResponseContext(
        business_name=data.get("display_name", "Our Business"),
        business_category=data.get("category", "generic"),
        business_description=data.get("description", ""),
        features=data.get("features", {}),
    )

    enabled = ctx.features
    response_map = _build_response_map(enabled)

    if use_llm:
        prompt = build_llm_prompt(ctx)
        logger.info(f"Calling LLM for business: {ctx.business_name}")

        raw_output = call_llm(prompt)

        if raw_output:
            logger.info("LLM generation successful")
            parsed_responses = parse_llm_output(raw_output, response_map)


            expected_count = len(response_map)
            min_acceptable = max(3, expected_count - 2)

            if len(parsed_responses) < min_acceptable:
                logger.warning(f"LLM returned {len(parsed_responses)} responses, expected {expected_count}. Using fallback.")
            else:

                if len(parsed_responses) < expected_count:
                    logger.warning(f"Padding LLM output: {len(parsed_responses)} -> {expected_count}")
                    parsed_responses += [""] * (expected_count - len(parsed_responses))


                parsed_responses = validate_and_fix_placeholders(parsed_responses, response_map)
                yaml_str = format_as_yaml(parsed_responses, enabled, response_map)


                gated = quality_gate_yaml(yaml_str, response_map)
                if gated is not None:
                    return gated
                else:
                    logger.warning("Quality gate rejected LLM output, using template fallback")
        else:
            logger.info("LLM unavailable, using template fallback.")


    return _generate_template_fallback(ctx)


def _generate_template_fallback(ctx: ResponseContext) -> str:
    """Generate basic responses when LLM is unavailable."""
    from .generators import generate_responses_template
    return generate_responses_template({
        "display_name": ctx.business_name,
        "features": ctx.features,
    })


def enhance_with_llm(template_yaml: str, data: dict[str, Any]) -> str:
    """
    Use LLM to enhance specific responses in a template.
    This is a lighter approach - generate template first, then improve key responses.
    """
    ctx = ResponseContext(
        business_name=data.get("display_name", "Our Business"),
        business_category=data.get("category", "generic"),
        business_description=data.get("description", ""),
        features=data.get("features", {}),
    )

    enhancement_prompt = f"""You are enhancing bot responses for a Telegram chatbot.

BUSINESS: {ctx.business_name}
CATEGORY: {ctx.business_category}
DESCRIPTION: {ctx.business_description}

Below is a set of template responses. Rewrite ONLY the GENERAL responses (greeting, goodbye, fallback, help, about) to be more personalized for this specific business. Keep the same structure and response keys.

TEMPLATE RESPONSES:
{template_yaml}

TASK:
Rewrite ONLY these responses to be more natural and personalized:
- intent_greeting
- intent_goodbye  
- intent_fallback
- intent_thanks
- intent_help
- intent_business_hours
- intent_location
- intent_contact
- intent_about

Keep all other responses unchanged. Return the complete YAML with only these 9 responses modified.
"""

    enhanced = call_llm(enhancement_prompt)

    if enhanced:
        return enhanced

    return template_yaml
