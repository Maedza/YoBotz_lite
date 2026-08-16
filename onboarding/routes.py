"""
Onboarding API routes — web self-onboarding endpoints.
Decoupled from running system; only writes to filesystem on explicit completion.
"""

import json
import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from .session import get_session_manager, OnboardingSession
from .validators import validate_step, ValidationError
from .generators import generate_preview, generate_business_config, generate_responses
from .generators import generate_products_json, generate_services_yaml

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/onboarding", tags=["onboarding"])


PROJECT_ROOT = Path(__file__).parent.parent
BUSINESSES_DIR = PROJECT_ROOT / "businesses"


class StartRequest(BaseModel):
    """Request to start a new onboarding session."""
    pass


class StartResponse(BaseModel):
    """Response with new session info and step 1 data."""
    session_id: str
    current_step: int
    total_steps: int = 5
    step_title: str
    step_fields: list[dict]


class StepRequest(BaseModel):
    """Request to submit data for a step."""
    session_id: str
    data: dict


class StepResponse(BaseModel):
    """Response after submitting a step."""
    success: bool
    current_step: int
    step_title: str
    step_fields: list[dict]
    errors: dict[str, str] = {}


class PreviewResponse(BaseModel):
    """Response with generated config preview."""
    session_id: str
    business_name: str
    files: dict[str, str]


class CompleteResponse(BaseModel):
    """Response after completing onboarding."""
    success: bool
    business_name: str
    message: str
    files_created: list[str]


class CancelResponse(BaseModel):
    """Response after cancelling onboarding."""
    success: bool
    message: str


STEPS = {
    1: {
        "title": "Basic Information",
        "description": "Tell us about your business",
        "fields": [
            {"name": "name", "type": "text", "label": "Business Name (slug)", "placeholder": "my_bakery", "hint": "Lowercase letters, numbers, underscores only"},
            {"name": "display_name", "type": "text", "label": "Display Name", "placeholder": "My Bakery"},
            {"name": "category", "type": "select", "label": "Business Category", "options": [
                {"value": "bakery", "label": "Bakery"},
                {"value": "restaurant", "label": "Restaurant"},
                {"value": "retail", "label": "Retail"},
                {"value": "salon", "label": "Salon / Spa"},
                {"value": "clinic", "label": "Clinic"},
                {"value": "generic", "label": "Other"},
            ]},
            {"name": "description", "type": "textarea", "label": "Description (optional)", "placeholder": "A brief description of your business..."},
        ],
    },
    2: {
        "title": "Features",
        "description": "What capabilities does your business need?",
        "fields": [
            {"name": "features.ordering", "type": "toggle", "label": "Ordering System", "hint": "Cart, checkout, order confirmations"},
            {"name": "features.reservation", "type": "toggle", "label": "Reservation Mode", "hint": "Strict time slots for offline payment businesses (shown if Ordering enabled)", "condition": "features.ordering"},
            {"name": "features.booking", "type": "toggle", "label": "Booking System", "hint": "Appointments for service businesses (salon, clinic)"},
            {"name": "features.accounts", "type": "toggle", "label": "Customer Accounts", "hint": "User profiles and order history"},
            {"name": "features.inventory", "type": "toggle", "label": "Inventory Management", "hint": "Stock tracking"},
        ],
    },
    3: {
        "title": "Contact & Hours",
        "description": "How can customers reach you?",
        "fields": [
            {"name": "address", "type": "text", "label": "Address"},
            {"name": "phone", "type": "text", "label": "Phone Number"},
            {"name": "email", "type": "email", "label": "Email"},
            {"name": "website", "type": "text", "label": "Website (optional)"},
            {"name": "timezone", "type": "select", "label": "Timezone", "options": [
                {"value": "Asia/Singapore", "label": "Singapore (SGT)"},
                {"value": "Asia/Kuala_Lumpur", "label": "Kuala Lumpur (MYT)"},
                {"value": "Asia/Hong_Kong", "label": "Hong Kong (HKT)"},
                {"value": "Asia/Tokyo", "label": "Tokyo (JST)"},
                {"value": "America/New_York", "label": "New York (EST)"},
                {"value": "America/Los_Angeles", "label": "Los Angeles (PST)"},
                {"value": "Europe/London", "label": "London (GMT)"},
            ]},
        ],
    },
    4: {
        "title": "Operational Settings",
        "description": "Fine-tune your business settings",
        "fields": [
            {"name": "product_source", "type": "select", "label": "Product Source", "hint": "How will you manage your products?", "condition": "features.ordering", "options": [
                {"value": "static", "label": "Static File (default)"},
                {"value": "apps_script", "label": "Google Sheets (via Apps Script)"},
            ]},
            {"name": "apps_script_url", "type": "text", "label": "Apps Script URL", "placeholder": "https://script.google.com/macros/s/.../exec", "hint": "Paste your deployed Google Apps Script web app URL", "condition": "features.ordering"},
            {"name": "sync_interval_minutes", "type": "number", "label": "Sync Interval (minutes)", "hint": "How often to sync products from sheet (default 60)", "condition": "features.ordering"},
            {"name": "min_order_amount", "type": "number", "label": "Minimum Order Amount", "hint": "Leave empty for no minimum", "condition": "features.ordering"},
            {"name": "min_booking_notice", "type": "number", "label": "Minimum Booking Notice (hours)", "hint": "How far in advance customers must book", "condition": "features.booking"},
            {"name": "hours_open", "type": "text", "label": "Default Opening Time", "placeholder": "09:00"},
            {"name": "hours_close", "type": "text", "label": "Default Closing Time", "placeholder": "18:00"},
        ],
    },
    5: {
        "title": "Bot Configuration",
        "description": "Connect your Telegram bot",
        "fields": [
            {"name": "BOT_TOKEN", "type": "text", "label": "Telegram Bot Token", "placeholder": "123456789:ABCdef...", "hint": "Get it from @BotFather"},
            {"name": "NOTIFICATION_BOT_TOKEN", "type": "text", "label": "Notification Bot Token (optional)", "placeholder": "Same as main or separate bot", "hint": "Leave empty to use main bot"},
            {"name": "BUSINESS_OWNER_CHAT_ID", "type": "text", "label": "Your Chat ID", "placeholder": "123456789", "hint": "Your Telegram user ID for admin notifications"},
        ],
    },
}


def _persist_config_blobs(vault, files_content: dict[str, str]):
    """
    Parse generated YAML/JSON strings and persist them as Redis config blobs
    so the business persists without relying on filesystem dirs.
    """
    blob_map = {
        "business_config.yaml": "config",
        "responses.yaml": "responses",
        "products.json": "products",
        "services.yaml": "services",
    }
    for filename, blob_name in blob_map.items():
        content = files_content.get(filename)
        if not content:
            continue
        try:
            if filename.endswith(".yaml"):
                data = yaml.safe_load(content)
            else:
                data = json.loads(content)
            if data:
                vault.set_config_blob(blob_name, data)
                logger.info(f"Persisted config blob '{blob_name}' to vault")
        except Exception as e:
            logger.warning(f"Failed to persist config blob '{blob_name}': {e}")


@router.post("/start", response_model=StartResponse)
async def start_onboarding():
    """Start a new onboarding session."""
    manager = get_session_manager()
    session = manager.create()

    step_info = STEPS[1]
    return StartResponse(
        session_id=session.session_id,
        current_step=session.current_step,
        step_title=step_info["title"],
        step_fields=step_info["fields"],
    )


@router.post("/step", response_model=StepResponse)
async def submit_step(req: StepRequest):
    """Submit data for current step, validate, and advance."""
    manager = get_session_manager()
    session = manager.get(req.session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    if session.completed:
        raise HTTPException(status_code=400, detail="Session already completed")


    errors = validate_step(session.current_step, req.data)
    if errors:
        step_info = STEPS[session.current_step]
        return StepResponse(
            success=False,
            current_step=session.current_step,
            step_title=step_info["title"],
            step_fields=step_info["fields"],
            errors=errors,
        )


    manager.update(req.session_id, req.data)


    if session.current_step == 1:
        session.business_name = req.data.get("name", "").strip()
        session.save()


    if session.current_step >= 5:
        session.completed = True
        manager.complete(req.session_id)
        return StepResponse(
            success=True,
            current_step=session.current_step,
            step_title="Complete",
            step_fields=[],
        )
    else:
        manager.advance(req.session_id)
        session = manager.get(req.session_id)
        step_info = STEPS[session.current_step]
        return StepResponse(
            success=True,
            current_step=session.current_step,
            step_title=step_info["title"],
            step_fields=step_info["fields"],
        )


@router.get("/preview/{session_id}", response_model=PreviewResponse)
async def preview_config(session_id: str):
    """Get preview of generated config files."""
    manager = get_session_manager()
    session = manager.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    if not session.business_name:
        raise HTTPException(status_code=400, detail="Business name not set")


    from .generators import CATEGORY_DEFAULTS
    cat_defaults = CATEGORY_DEFAULTS.get(session.data.get("category", "generic"), {})


    complete_data = {
        **cat_defaults,
        **session.data,
        "name": session.business_name,
        "display_name": session.data.get("display_name", session.business_name),
    }

    files = generate_preview(complete_data)

    return PreviewResponse(
        session_id=session_id,
        business_name=session.business_name,
        files=files,
    )


@router.post("/complete/{session_id}", response_model=CompleteResponse)
async def complete_onboarding(session_id: str):
    """Write all config files to businesses/ directory."""
    manager = get_session_manager()
    session = manager.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    if not session.business_name:
        raise HTTPException(status_code=400, detail="Business name not set")

    business_dir = BUSINESSES_DIR / session.business_name
    if business_dir.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Business '{session.business_name}' already exists"
        )


    from .generators import CATEGORY_DEFAULTS
    cat_defaults = CATEGORY_DEFAULTS.get(session.data.get("category", "generic"), {})


    complete_data = {
        **cat_defaults,
        **session.data,
        "name": session.business_name,
        "display_name": session.data.get("display_name", session.business_name),
    }


    files_content = generate_preview(complete_data)
    secrets = {
        "BOT_TOKEN": session.data.get("BOT_TOKEN", ""),
        "NOTIFICATION_BOT_TOKEN": session.data.get("NOTIFICATION_BOT_TOKEN", session.data.get("BOT_TOKEN", "")),
        "BUSINESS_OWNER_CHAT_ID": session.data.get("BUSINESS_OWNER_CHAT_ID", ""),
    }

    files_created = []

    try:

        business_dir.mkdir(parents=True, exist_ok=True)


        for filename, content in files_content.items():
            filepath = business_dir / filename
            filepath.write_text(content, encoding="utf-8")
            files_created.append(filename)
            logger.info(f"Created {filepath}")


        env_content = f"# {complete_data['display_name']} — Secrets\n"
        env_content += f"# Managed by Onboarding System\n\n"
        for key, value in secrets.items():
            if value:
                env_content += f"{key}={value}\n"

        env_path = business_dir / ".env"
        env_path.write_text(env_content, encoding="utf-8")
        files_created.append(".env")


        try:
            from core.business_vault import BusinessVault
            vault = BusinessVault(session.business_name)
            for key, value in secrets.items():
                if value:
                    vault.set_secret(key, value)


            if secrets.get("BOT_TOKEN"):
                vault.set_secret("bot_token", secrets["BOT_TOKEN"])
            if secrets.get("NOTIFICATION_BOT_TOKEN"):
                vault.set_secret("notification_bot_token", secrets["NOTIFICATION_BOT_TOKEN"])
            if secrets.get("BUSINESS_OWNER_CHAT_ID"):
                vault.set_secret("chat_ids", secrets["BUSINESS_OWNER_CHAT_ID"])


            _persist_config_blobs(vault, files_content)

            logger.info(f"Stored secrets + config blobs in vault for {session.business_name}")
        except Exception as e:
            logger.warning(f"Could not store secrets in vault: {e}")


        session.completed = True
        manager.complete(session_id)

        return CompleteResponse(
            success=True,
            business_name=session.business_name,
            message=f"Business '{session.business_name}' created successfully!",
            files_created=files_created,
        )

    except Exception as e:

        logger.error(f"Onboarding failed: {e}")
        if business_dir.exists():
            import shutil
            shutil.rmtree(business_dir)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cancel/{session_id}", response_model=CancelResponse)
async def cancel_onboarding(session_id: str):
    """Cancel and cleanup an onboarding session."""
    manager = get_session_manager()
    session = manager.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    manager.delete(session_id)

    return CancelResponse(
        success=True,
        message="Onboarding session cancelled"
    )


@router.get("/session/{session_id}")
async def get_session_status(session_id: str):
    """Get current session status."""
    manager = get_session_manager()
    session = manager.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    return {
        "session_id": session.session_id,
        "current_step": session.current_step,
        "total_steps": 5,
        "completed": session.completed,
        "business_name": session.business_name,
    }
