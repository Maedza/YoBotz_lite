from enum import Enum, auto

class OrderState(Enum):
    IDLE = auto()
    ORDERING = auto() 
    BOOKING = auto()

class OrderSubState(Enum):
    AWAITING_CATEGORY_SELECTION = auto()
    AWAITING_PRODUCT_SELECTION = auto()
    AWAITING_VARIANT_SELECTION = auto()
    AWAITING_MORE_ITEMS = auto()
    AWAITING_CONFIRMATION = auto()
    CART_EDITING = auto()
    AWAITING_RESERVATION_DATETIME = auto()
    NONE = auto()
