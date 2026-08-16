"""
Unified Messaging Gateway

A simplified, unified messaging solution for Telegram.
"""

from .models import (
    UnifiedMessage,
    DeliveryInfo,
    DeliveryStatus,
    Platform,
    MediaType,
    MediaAttachment
)
from .config import PlatformConfig, GatewayConfig, load_config
from .router import MessageRouter
from .user_mapper import UserMapper
from .delivery_tracker import DeliveryTracker
from .message_queue import MessageQueue
from .adapters import PlatformAdapter, TelegramAdapter

__version__ = "1.0.0"

__all__ = [

    'UnifiedMessage',
    'DeliveryInfo',
    'DeliveryStatus',
    'Platform',
    'MediaType',
    'MediaAttachment',
    'PlatformConfig',

    'GatewayConfig',
    'load_config',

    'MessageRouter',
    'UserMapper',
    'DeliveryTracker',
    'MessageQueue',

    'PlatformAdapter',
    'TelegramAdapter'
]
