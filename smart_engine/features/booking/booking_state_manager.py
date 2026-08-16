from datetime import datetime
from typing import Dict, Any, Optional

from smart_engine.features.booking.booking_enums import BookingState

class BookingStateManager:
    """Manages ONLY booking flow state - completely separate from management"""

    def __init__(self, session: dict):
        self.session = session
        self._ensure_booking_state()
        self._fix_deserialized_state()

    def _ensure_booking_state(self):
        if "booking_flow" not in self.session:
            self.session["booking_flow"] = {
                "active": False,
                "current_state": BookingState.IDLE,
                "current_booking": {},
                "locked_slot_info": None,
                "started_at": None
            }

    def _fix_deserialized_state(self):
        """Fix deserialized session where current_state might be a string"""
        booking_flow = self.session.get("booking_flow", {})
        current_state = booking_flow.get("current_state")
        if isinstance(current_state, str):
            try:
                booking_flow["current_state"] = BookingState[current_state]
            except KeyError:
                booking_flow["current_state"] = BookingState.IDLE
            self.session["booking_flow"] = booking_flow

    def is_active(self) -> bool:
        booking_flow = self.session.get("booking_flow", {})
        return booking_flow.get("active", False)

    def get_state(self) -> BookingState:
        booking_flow = self.session.get("booking_flow", {})
        return booking_flow.get("current_state", BookingState.IDLE)

    def get_booking_data(self) -> Dict[str, Any]:
        booking_flow = self.session.get("booking_flow", {})
        return booking_flow.get("current_booking", {}).copy()

    def start_booking(self):
        if "booking_flow" not in self.session:
            self.session["booking_flow"] = {}
        self.session["booking_flow"].update({
            "active": True,
            "current_state": BookingState.SERVICE_SELECTION,
            "current_booking": {},
            "locked_slot_info": None,
            "started_at": datetime.now().isoformat()
        })

    def update_booking_data(self, updates: Dict[str, Any]):
        if "booking_flow" not in self.session:
            self.session["booking_flow"] = {"current_booking": {}}
        elif "current_booking" not in self.session["booking_flow"]:
            self.session["booking_flow"]["current_booking"] = {}
        self.session["booking_flow"]["current_booking"].update(updates)

    def set_state(self, state: BookingState):
        if "booking_flow" not in self.session:
            self.session["booking_flow"] = {}
        self.session["booking_flow"]["current_state"] = state

    def set_locked_slot(self, slot_info: Dict[str, Any]):
        if "booking_flow" not in self.session:
            self.session["booking_flow"] = {}
        self.session["booking_flow"]["locked_slot_info"] = slot_info

    def get_locked_slot(self) -> Optional[Dict[str, Any]]:
        booking_flow = self.session.get("booking_flow", {})
        return booking_flow.get("locked_slot_info")

    def cancel_booking(self):
        booking_flow = self.session.get("booking_flow", {})
        locked_slot = booking_flow.get("locked_slot_info")
        if "booking_flow" not in self.session:
            self.session["booking_flow"] = {}
        self.session["booking_flow"].update({
            "active": False,
            "current_state": BookingState.IDLE,
            "current_booking": {},
            "locked_slot_info": None,
            "started_at": None
        })
        return locked_slot

    def complete_booking(self):
        booking_flow = self.session.get("booking_flow", {})
        booking_data = booking_flow.get("current_booking", {}).copy()
        if "booking_flow" not in self.session:
            self.session["booking_flow"] = {}
        self.session["booking_flow"].update({
            "active": False,
            "current_state": BookingState.IDLE,
            "current_booking": {},
            "locked_slot_info": None,
            "started_at": None
        })
        return booking_data
