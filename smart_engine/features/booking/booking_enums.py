from enum import Enum, auto

class BookingState(Enum):
    SERVICE_SELECTION = auto()
    PARTY_SIZE = auto()
    TOPIC = auto()
    DATETIME_SELECTION = auto()
    NAME_COLLECTION = auto()
    SPECIAL_REQUESTS = auto()
    CONFIRMATION = auto()
    IDLE = auto()

class BookingSlotState(Enum):
    AVAILABLE = auto()
    LOCKED = auto()
    BOOKED = auto()
    EXPIRED = auto()

class BookingManagementState(Enum):
    IDLE = "idle"
    AWAITING_CANCELLATION_SELECTION = "awaiting_selection"
    AWAITING_CANCELLATION_CONFIRMATION = "awaiting_confirmation"


CATEGORY_BOOKING_FLOW = {
    "restaurant": [
        BookingState.SERVICE_SELECTION,
        BookingState.PARTY_SIZE,
        BookingState.DATETIME_SELECTION,
        BookingState.NAME_COLLECTION,
        BookingState.CONFIRMATION
    ],
    "salon": [
        BookingState.SERVICE_SELECTION,
        BookingState.DATETIME_SELECTION,
        BookingState.NAME_COLLECTION,
        BookingState.CONFIRMATION
    ],
    "consultant": [
        BookingState.SERVICE_SELECTION,
        BookingState.TOPIC,
        BookingState.DATETIME_SELECTION,
        BookingState.NAME_COLLECTION,
        BookingState.CONFIRMATION
    ],
    "bakery": [
        BookingState.SERVICE_SELECTION,
        BookingState.DATETIME_SELECTION,
        BookingState.NAME_COLLECTION,
        BookingState.SPECIAL_REQUESTS,
        BookingState.CONFIRMATION
    ]
}
