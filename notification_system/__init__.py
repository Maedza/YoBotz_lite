"""
Simple Notification System
"""
from .models import Notification, NotificationRole, NotificationPriority
from .service import get_notification_service, NotificationService

__version__ = "1.0.0"
__all__ = [
    'Notification',
    'NotificationRole',
    'NotificationPriority',
    'get_notification_service',
    'NotificationService'
]
