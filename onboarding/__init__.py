"""
Onboarding module — Web self-onboarding backend.
Decoupled from running system; only writes to filesystem on explicit completion.
"""

from .session import OnboardingSession, SessionManager
from .generators import (
    generate_business_config,
    generate_responses,
    generate_products_json,
    generate_services_yaml,
)
from .validators import validate_step, ValidationError

__all__ = [
    "OnboardingSession",
    "SessionManager",
    "generate_business_config",
    "generate_responses",
    "generate_products_json",
    "generate_services_yaml",
    "validate_step",
    "ValidationError",
]
