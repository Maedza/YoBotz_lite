"""
Platform Adapters Package

Exports all platform adapter classes.
"""

from .base import PlatformAdapter
from .telegram import TelegramAdapter

__all__ = [
    'PlatformAdapter',
    'TelegramAdapter'
]
