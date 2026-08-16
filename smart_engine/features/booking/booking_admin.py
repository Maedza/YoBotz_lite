import logging
from datetime import datetime
from typing import Any, Dict, Optional, List

from smart_engine.core.utils.response_channel import BotReply
from smart_engine.features.booking.booking_enums import BookingManagementState

logger = logging.getLogger(__name__)


class BookingAdmin:
    """Manages booking admin (view/cancel) - completely separate"""

    def __init__(self, session: Dict[str, Any], manager: Any):
        self.session = session
        self.manager = manager
        self._ensure_management_state()

    def _ensure_management_state(self):
        if "booking_management" not in self.session:
            self.session["booking_management"] = {
                "active": False,
                "state": BookingManagementState.IDLE.value,
                "candidates": [],
                "selected_booking": None,
                "started_at": None
            }

    def get_candidates(self) -> List[Dict[str, Any]]:
        self._ensure_management_state()
        booking_mgmt = self.session.get("booking_management", {})
        return booking_mgmt.get("candidates", []).copy()

    def start_cancellation(self, bookings: List[Dict[str, Any]]):
        self._ensure_management_state()
        self.session["booking_management"].update({
            "active": True,
            "state": BookingManagementState.AWAITING_CANCELLATION_SELECTION.value,
            "candidates": bookings,
            "selected_booking": None,
            "started_at": datetime.now().isoformat()
        })

    def set_selected_booking(self, booking: Dict[str, Any]):
        self._ensure_management_state()
        if "booking_management" not in self.session:
            self.session["booking_management"] = {}
        self.session["booking_management"]["selected_booking"] = booking
        self.session["booking_management"]["state"] = BookingManagementState.AWAITING_CANCELLATION_CONFIRMATION.value
        self.session["booking_management"]["active"] = True

    def confirm_cancellation(self) -> Optional[Dict[str, Any]]:
        self._ensure_management_state()
        booking_mgmt = self.session.get("booking_management", {})
        cancelled_booking = booking_mgmt.get("selected_booking")
        self.cancel_management()
        return cancelled_booking

    def cancel_management(self):
        self._ensure_management_state()
        self.session["booking_management"].update({
            "active": False,
            "state": BookingManagementState.IDLE.value,
            "candidates": [],
            "selected_booking": None,
            "started_at": None
        })

    def is_awaiting_selection(self) -> bool:
        self._ensure_management_state()
        booking_mgmt = self.session.get("booking_management", {})
        return booking_mgmt.get("state") == BookingManagementState.AWAITING_CANCELLATION_SELECTION.value

    def is_awaiting_confirmation(self) -> bool:
        self._ensure_management_state()
        booking_mgmt = self.session.get("booking_management", {})
        return booking_mgmt.get("state") == BookingManagementState.AWAITING_CANCELLATION_CONFIRMATION.value

    def handle_message(self, message: str) -> Optional[BotReply]:
        direct_cancel_reply = self._handle_direct_cancellation_command(message)
        if direct_cancel_reply:
            return direct_cancel_reply

        msg_lower = message.lower().strip()
        if msg_lower in ["cancel booking", "cancel bookings", "cancel my booking"]:
            return self.show_cancellation_prompt()

        if self.session.get("_awaiting_multiple_cancellation_confirm"):
            return self._handle_multiple_cancellation_confirmation(message)

        if self.is_awaiting_confirmation():
            return self._handle_cancellation_confirmation(message)
        elif self.is_awaiting_selection():
            return self._handle_cancellation_selection(message)

        if self._is_booking_id(message):
            return self._handle_booking_cancellation(message)

        if message.isdigit():
            booking_index = int(message) - 1
            return self._handle_numeric_booking_selection(booking_index)

        msg_lower = message.lower().strip()
        if msg_lower in ["my bookings", "view bookings", "show bookings", "bookings", "list bookings"]:
            return self.show_all_bookings()

        return None

    def _is_booking_id(self, message: str) -> bool:
        if len(message) == 8 and all(c in '0123456789abcdef' for c in message.lower()):
            return True
        return False

    def _handle_numeric_booking_selection(self, booking_index: int) -> BotReply:
        try:
            user_bookings = self.manager._get_user_bookings()

            if not user_bookings:
                return BotReply(
                    text=self.manager.response_handler.get_response(
                        "no_bookings_found"),
                    meta={"intent": "book_service", "stage": "no_bookings"}
                )

            if 0 <= booking_index < len(user_bookings):
                booking = user_bookings[booking_index]
                booking_id_short = booking.get('id', '')[:8]
                return self._handle_booking_cancellation(booking_id_short)
            else:
                error_text = self.manager._get_safe_formatted_response(
                    "invalid_booking_selection",
                    max_number=len(user_bookings)
                )

                return BotReply(
                    text=error_text,
                    meta={"intent": "book_service",
                          "stage": "invalid_selection"}
                )

        except Exception:
            logger.exception("Error handling numeric selection")
            return BotReply(
                text=self.manager.response_handler.get_response("selection_error"),
                meta={"intent": "book_service", "stage": "selection_error"}
            )

    def show_cancellation_prompt(self, direct_booking_ref: Optional[str] = None) -> BotReply:
        user_bookings = self.manager._get_user_bookings()

        if not user_bookings:
            return BotReply(
                text=self.manager.response_handler.get_response("no_bookings_found"),
                meta={"intent": "book_service", "stage": "no_bookings", "tool_completed": True}
            )

        if direct_booking_ref:
            if direct_booking_ref.isdigit():
                booking_index = int(direct_booking_ref) - 1
                if 0 <= booking_index < len(user_bookings):
                    booking = user_bookings[booking_index]
                    return self._handle_booking_cancellation(booking.get('id', '')[:8])
                else:
                    error_text = self.manager._get_safe_formatted_response(
                        "invalid_booking_selection",
                        max_number=len(user_bookings)
                    )
                    return BotReply(
                        text=error_text,
                        meta={"intent": "book_service",
                              "stage": "invalid_selection"}
                    )

            elif self._is_booking_id(direct_booking_ref):
                return self._handle_booking_cancellation(direct_booking_ref)

            else:
                self.start_cancellation(user_bookings)
                self.manager._update_session_state({
                    "booking_management": self.session["booking_management"]
                })

                error_msg = f"❌ Booking reference '{direct_booking_ref}' not found. Please select from the list below:"
                bookings_display = self._format_bookings_display(
                    "cancellation_prompt", "cancel_prompt")
                return BotReply(
                    text=f"{error_msg}\n\n{bookings_display.text}",
                    meta=bookings_display.meta
                )

        self.start_cancellation(user_bookings)
        self.manager._update_session_state({
            "booking_management": self.session["booking_management"]
        })

        return self._format_bookings_display("cancellation_prompt", "cancel_prompt")

    def _handle_direct_cancellation_command(self, message: str) -> Optional[BotReply]:
        """Handle commands like 'cancel booking 1' or 'cancel booking 1, 3' or 'cancel booking abc123'"""
        msg_lower = message.lower().strip()

        if not msg_lower.startswith('cancel booking'):
            return None

        parts = message.split()
        if len(parts) < 3:
            return None

        booking_refs = ' '.join(parts[2:])

        user_bookings = self.manager._get_user_bookings()
        if not user_bookings:
            return BotReply(
                text=self.manager.response_handler.get_response("no_bookings_found"),
                meta={"intent": "book_service", "stage": "no_bookings"}
            )

        refs_split = booking_refs.replace(',', ' ').split()

        refs = [r.strip() for r in refs_split if r.strip() and r.strip() not in ['cancel', 'booking']]

        booking_ref = refs[0] if refs else ''
        if len(refs) == 1:

            if booking_ref.isdigit():
                booking_index = int(booking_ref) - 1
                if 0 <= booking_index < len(user_bookings):
                    booking = user_bookings[booking_index]
                    return self._handle_booking_cancellation(booking.get('id', '')[:8])
                else:
                    error_text = self.manager._get_safe_formatted_response(
                        "invalid_booking_selection",
                        max_number=len(user_bookings)
                    )
                    return BotReply(
                        text=error_text,
                        meta={"intent": "book_service",
                              "stage": "invalid_selection"}
                    )

            elif self._is_booking_id(booking_ref):
                return self._handle_booking_cancellation(booking_ref)

        elif len(refs) > 1:
            return self._handle_multiple_cancellations(refs, user_bookings)

        self.start_cancellation(user_bookings)
        self.manager._update_session_state({
            "booking_management": self.session["booking_management"]
        })

        error_msg = f"❌ Booking reference '{booking_ref}' not found. Please select from the list below:"
        bookings_display = self._format_bookings_display(
            "cancellation_prompt", "cancel_prompt")
        return BotReply(
            text=f"{error_msg}\n\n{bookings_display.text}",
            meta=bookings_display.meta
        )

    def show_all_bookings(self) -> BotReply:
        user_bookings = self.manager._get_user_bookings()

        if not user_bookings:
            return BotReply(
                text=self.manager.response_handler.get_response("no_bookings_found"),
                meta={"intent": "book_service", "stage": "no_bookings", "tool_completed": True}
            )

        booking_text = ""
        for i, booking in enumerate(user_bookings, 1):
            service = booking.get("service_name", "Unknown")
            dt_display = booking.get(
                "datetime_display", booking.get("datetime", "Unknown"))
            status = booking.get("status", "Unknown")
            booking_id = booking.get("id", "Unknown")[:8]

            status_emoji = "✅" if status == "confirmed" else "⏳" if status == "pending" else "❌"

            booking_text += f"{i}. **{service}**\n"
            booking_text += f"   📅 {dt_display}\n"
            booking_text += f"   {status_emoji} {status.title()}\n"
            booking_text += f"   🆔 ID: {booking_id}\n\n"

        display_text = self.manager._get_safe_formatted_response(
            "bookings_list",
            bookings_list=booking_text
        )

        return BotReply(
            text=display_text,
            meta={"intent": "book_service", "stage": "bookings_list"}
        )

    def _format_bookings_display(self, response_key: str, meta_stage: str) -> BotReply:
        try:
            user_bookings = self.get_candidates()

            if not user_bookings:
                return BotReply(
                    text=self.manager.response_handler.get_response(
                        "no_bookings_found"),
                    meta={"intent": "book_service", "stage": "no_bookings"}
                )

            booking_text = ""
            for i, booking in enumerate(user_bookings, 1):
                service = booking.get("service_name", "Unknown")
                dt_display = booking.get(
                    "datetime_display", booking.get("datetime", "Unknown"))
                status = booking.get("status", "Unknown")
                booking_id = booking.get("id", "Unknown")[:8]

                status_emoji = "✅" if status == "confirmed" else "⏳" if status == "pending" else "❌"

                booking_text += f"{i}. **{service}**\n"
                booking_text += f"   📅 {dt_display}\n"
                booking_text += f"   {status_emoji} {status.title()}\n"
                booking_text += f"   🆔 ID: {booking_id}\n\n"

            raw_template = self.manager.response_handler.responses.get(response_key, "")
            if raw_template:
                try:
                    display_text = raw_template.format(bookings_list=booking_text)
                except KeyError:
                    display_text = self.manager._get_safe_formatted_response(response_key, bookings_list=booking_text)
            else:
                display_text = self.manager._get_safe_formatted_response(response_key, bookings_list=booking_text)

            return BotReply(
                text=display_text,
                meta={"intent": "book_service", "stage": meta_stage}
            )

        except Exception:
            logger.exception("Error formatting bookings")
            return BotReply(
                text=self.manager.response_handler.get_response(
                    "booking_management_error"),
                meta={"intent": "book_service", "stage": "error"}
            )

    def _handle_booking_cancellation(self, booking_id: str) -> BotReply:
        booking = self.manager._find_booking_by_id(booking_id)
        if not booking:
            return BotReply(
                text=self.manager.response_handler.get_response("booking_not_found"),
                meta={"intent": "book_service", "stage": "booking_not_found"}
            )

        self.set_selected_booking(booking)

        self.manager._update_session_state({
            "booking_management": self.session["booking_management"]
        })

        service_name = booking.get('service_name', 'Unknown service')
        datetime_str = booking.get(
            'datetime_display', booking.get('datetime', 'Unknown time'))

        raw_template = self.manager.response_handler.responses.get("confirm_cancellation", "")
        if raw_template:
            try:
                confirmation_text = raw_template.format(
                    service_name=service_name,
                    datetime=datetime_str,
                    booking_id=booking_id
                )
            except KeyError:
                confirmation_text = self.manager._get_safe_formatted_response(
                    "confirm_cancellation",
                    service_name=service_name,
                    datetime=datetime_str,
                    booking_id=booking_id
                )
        else:
            confirmation_text = self.manager._get_safe_formatted_response(
                "confirm_cancellation",
                service_name=service_name,
                datetime=datetime_str,
                booking_id=booking_id
            )

        return BotReply(
            text=confirmation_text,
            meta={"intent": "book_service", "stage": "confirm_cancellation"}
        )

    def _handle_cancellation_selection(self, message: str) -> BotReply:
        msg_lower = message.lower().strip()

        if msg_lower in ['cancel', 'quit', 'exit', 'no', 'back']:
            self.cancel_management()
            self.manager._update_session_state({
                "booking_management": self.session["booking_management"]
            })
            return BotReply(
                text=self.manager.response_handler.get_response("cancellation_canceled"),
                meta={"intent": "book_service", "stage": "cancellation_canceled"}
            )

        if message.isdigit():
            booking_index = int(message) - 1
            candidates = self.get_candidates()

            if 0 <= booking_index < len(candidates):
                booking = candidates[booking_index]
                booking_id = booking.get('id', '')[:8]

                return self._handle_booking_cancellation(booking_id)
            else:
                error_text = self.manager._get_safe_formatted_response(
                    "invalid_booking_selection",
                    max_number=len(candidates)
                )
                return BotReply(
                    text=error_text,
                    meta={"intent": "book_service",
                          "stage": "invalid_selection"}
                )
        else:
            return self.show_cancellation_prompt()

    def _handle_cancellation_confirmation(self, message: str) -> BotReply:
        msg_lower = message.lower().strip()

        if msg_lower in ['yes', 'y', 'confirm', 'cancel']:
            cancelled_booking = self.confirm_cancellation()
            if not cancelled_booking:
                return BotReply(
                    text=self.manager.response_handler.get_response(
                        "no_booking_to_cancel"),
                    meta={"intent": "book_service", "stage": "no_booking"}
                )

            try:
                bookings = self.manager.load_bookings()

                bookings = [b for b in bookings if not (
                    b.get('id') == cancelled_booking.get('id') and
                    b.get('user_session') == cancelled_booking.get(
                        'user_session')
                )]

                self.manager.save_json(self.manager.bookings_file, bookings)

                self.manager._send_booking_cancellation_notification(cancelled_booking)

                response_text = self.manager.response_handler.get_response(
                    "cancellation_successful")
                return BotReply(
                    text=response_text,
                    meta={"intent": "book_service",
                          "stage": "cancellation_complete", "tool_completed": True}
                )

            except Exception:
                logger.exception("Error processing cancellation")
                return BotReply(
                    text=self.manager.response_handler.get_response(
                        "cancellation_error"),
                    meta={"intent": "book_service",
                          "stage": "cancellation_error"}
                )

        elif msg_lower in ['no', 'n', 'keep']:
            self.cancel_management()
            return BotReply(
                text=self.manager.response_handler.get_response(
                    "cancellation_canceled"),
                meta={"intent": "book_service",
                      "stage": "cancellation_canceled"}
            )

        else:
            return BotReply(
                text=self.manager.response_handler.get_response(
                    "invalid_confirmation"),
                meta={"intent": "book_service",
                      "stage": "invalid_confirmation"}
            )

    def _handle_multiple_cancellations(self, refs: List[str], user_bookings: List[Dict[str, Any]]) -> BotReply:
        bookings_to_cancel = []

        for ref in refs:
            if ref.isdigit():
                booking_index = int(ref) - 1
                if 0 <= booking_index < len(user_bookings):
                    bookings_to_cancel.append(user_bookings[booking_index])

            elif self._is_booking_id(ref):
                for booking in user_bookings:
                    if booking.get('id', '').startswith(ref):
                        bookings_to_cancel.append(booking)
                        break

        if not bookings_to_cancel:
            error_text = self.manager._get_safe_formatted_response(
                "invalid_booking_selection",
                max_number=len(user_bookings)
            )
            return BotReply(
                text=error_text,
                meta={"intent": "book_service", "stage": "invalid_selection"}
            )

        confirmations = []
        for i, booking in enumerate(bookings_to_cancel, 1):
            service_name = booking.get('service_name', 'Unknown')
            dt_display = booking.get('datetime_display', booking.get('datetime', 'Unknown time'))
            confirmations.append(f"{i}. **{service_name}** on {dt_display}")

        confirmation_text = f"You're about to cancel {len(bookings_to_cancel)} booking(s):\n\n" + '\n'.join(confirmations) + "\n\n⚠️ Are you sure? Type 'yes' to confirm or 'no' to cancel."

        self.session["_bookings_to_cancel"] = bookings_to_cancel
        self.session["_awaiting_multiple_cancellation_confirm"] = True
        self.manager._update_session_state({
            "_bookings_to_cancel": bookings_to_cancel,
            "_awaiting_multiple_cancellation_confirm": True
        })

        return BotReply(
            text=confirmation_text,
            meta={"intent": "book_service", "stage": "confirm_multiple_cancellation"}
        )

    def _handle_multiple_cancellation_confirmation(self, message: str) -> BotReply:
        msg_lower = message.lower().strip()

        if msg_lower in ['yes', 'y', 'confirm', 'cancel']:
            bookings_to_cancel = self.session.get("_bookings_to_cancel", [])

            if not bookings_to_cancel:
                return BotReply(
                    text=self.manager.response_handler.get_response("no_booking_to_cancel"),
                    meta={"intent": "book_service", "stage": "no_booking"}
                )

            try:
                bookings = self.manager.load_bookings()

                cancelled_ids = {b.get('id') for b in bookings_to_cancel}

                bookings = [b for b in bookings if b.get('id') not in cancelled_ids]

                self.manager.save_json(self.manager.bookings_file, bookings)

                self.session.pop("_bookings_to_cancel", None)
                self.session.pop("_awaiting_multiple_cancellation_confirm", None)
                self.manager._update_session_state({
                    "_bookings_to_cancel": None,
                    "_awaiting_multiple_cancellation_confirm": None
                })

                return BotReply(
                    text=f"✅ {len(bookings_to_cancel)} booking(s) cancelled successfully!",
                    meta={"intent": "book_service",
                          "stage": "cancellation_complete", "tool_completed": True}
                )

            except Exception:
                logger.exception("Error processing multiple cancellations")
                return BotReply(
                    text=self.manager.response_handler.get_response("cancellation_error"),
                    meta={"intent": "book_service",
                          "stage": "cancellation_error"}
                )

        elif msg_lower in ['no', 'n', 'keep']:
            self.session.pop("_bookings_to_cancel", None)
            self.session.pop("_awaiting_multiple_cancellation_confirm", None)
            self.manager._update_session_state({
                "_bookings_to_cancel": None,
                "_awaiting_multiple_cancellation_confirm": None
            })
            return BotReply(
                text="Cancellations cancelled. Your bookings are still active.",
                meta={"intent": "book_service",
                      "stage": "cancellation_canceled"}
            )

        else:
            return BotReply(
                text=self.manager.response_handler.get_response("invalid_confirmation"),
                meta={"intent": "book_service",
                      "stage": "invalid_confirmation"}
            )
