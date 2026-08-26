import logging
import os
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
import pytz
from typing import Optional, Dict, Any, List

from smart_engine.core.utils.response_channel import BotReply
from smart_engine.core.response_handler import ResponseHandler
from smart_engine.features.ordering.ordering_enums import OrderState
from smart_engine.core.session_manager import SessionManager

from smart_engine.features.booking.booking_enums import BookingState, BookingSlotState, CATEGORY_BOOKING_FLOW

from smart_engine.features.booking.booking_state_manager import BookingStateManager
from smart_engine.features.booking.booking_admin import BookingAdmin

logger = logging.getLogger(__name__)

class BookingManager:
    def __init__(self, business_name: str, session: dict, response_handler: ResponseHandler, session_manager: SessionManager = None, force_category: str = None):
        self.business_name = business_name
        self.session = session
        self.response_handler = response_handler
        self.session_manager = session_manager
        self.session_id = session.get("session_id")
        self.force_category = force_category

        self.booking_state = BookingStateManager(session)
        self.booking_admin = BookingAdmin(session, manager=self)

        self.business_dir = os.path.join(self._root_dir(), "businesses", self.business_name)
        self.bookings_file = os.path.join(self.business_dir, "bookings.json")
        self.locks_file = os.path.join(self.business_dir, "locks.json")

        self.business_config = self._load_business_config()
        self.timezone = pytz.timezone(
            self.business_config.get("timezone", "UTC"))

        self.ensure_file(self.bookings_file)
        self.ensure_file(self.locks_file)
        self.load_services()
        self.load_bookable_products()
        self.merge_bookable()

    def _update_session_state(self, updates: Dict[str, Any]):

        self.session.update(updates)

        if "booking_flow" in self.session:

            booking_flow = self.session["booking_flow"].copy()
            current_state = booking_flow.get("current_state")
            if isinstance(current_state, BookingState):
                booking_flow["current_state"] = current_state.value
            updates["booking_flow"] = booking_flow

        if "booking_management" in self.session:
            updates["booking_management"] = self.session["booking_management"]

        if self.session_manager and self.session_id:
            try:
                parts = self.session_id.split('_')
                if len(parts) >= 2:
                    user_id = parts[0]
                    business_name = self.business_name

                    self.session_manager.update_session(
                        user_id, business_name, updates)

            except Exception:
                logger.exception("Error updating session state")

    def _load_business_config(self) -> Dict[str, Any]:
        config_path = os.path.join(self.business_dir, "business_config.yaml")

        if os.path.exists(config_path):
            import yaml
            with open(config_path) as f:
                config = yaml.safe_load(f)
                return config or {}

        return {}

    @staticmethod
    def _root_dir() -> str:
        return str(Path(__file__).resolve().parents[3])

    def ensure_file(self, path):
        try:
            if not os.path.exists(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    json.dump([], f)
        except Exception:
            logger.warning("Could not create %s: will be created lazily on save", path)

    def load_json(self, path):
        if not os.path.exists(path):
            return []
        try:
            with open(path) as f:
                content = f.read().strip()
                return json.loads(content) if content else []
        except Exception:
            logger.warning("Corrupted %s, treating as empty", path)
            return []

    def save_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_services(self):
        path = os.path.join(self.business_dir, "services.yaml")
        if not os.path.exists(path):
            self.services = []
            return
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        self.services = data.get("services", [])

    def load_bookable_products(self):
        path = os.path.join(self.business_dir, "products.json")
        if not os.path.exists(path):
            self.bookable_products = []
            return
        products = self.load_json(path)
        self.bookable_products = [
            p for p in products if isinstance(p, dict) and p.get("bookable")]

    def merge_bookable(self):
        self.all_bookable = []
        for s in self.services:
            if isinstance(s, dict):
                s["source"] = "service"
                self.all_bookable.append(s)
        for p in self.bookable_products:
            if isinstance(p, dict):
                p["source"] = "product"
                self.all_bookable.append(p)

    def load_locks(self):
        return self.load_json(self.locks_file)

    def save_locks(self, locks: list):
        self.save_json(self.locks_file, locks)

    def lock_slot(self, service_name: str, dt: datetime, extra_key=None) -> Optional[BotReply]:
        """Lock a time slot for booking. Returns BotReply if slot is already locked."""
        now = datetime.utcnow()
        expires_at = now + timedelta(minutes=5)
        locks = self.load_locks()

        locks = [l for l in locks if datetime.fromisoformat(
            l["expires_at"]) > now]

        for lock in locks:
            conflict = (lock["service_name"] ==
                        service_name and lock["datetime"] == dt.isoformat())
            if extra_key:
                conflict = conflict and lock.get("extra_key") == extra_key
            if conflict:
                return BotReply(
                    text=self.response_handler.get_response("slot_locked"),
                    meta={"intent": "book_service",
                          "stage": "slot_unavailable"}
                )

        lock_data = {
            "service_name": service_name,
            "datetime": dt.isoformat(),
            "locked_by": self.session.get("session_id", str(uuid.uuid4())),
            "status": BookingSlotState.LOCKED.value,
            "expires_at": expires_at.isoformat()
        }
        if extra_key:
            lock_data["extra_key"] = extra_key
        locks.append(lock_data)
        self.save_locks(locks)

        self.booking_state.set_locked_slot(lock_data)
        return None

    def release_slot(self):
        lock_info = self.booking_state.get_locked_slot()
        if not lock_info:
            return
        locks = self.load_locks()
        locks = [l for l in locks if not (l["service_name"] == lock_info["service_name"] and
                                          l["datetime"] == lock_info["datetime"] and
                                          l["locked_by"] == lock_info["locked_by"])]
        self.save_locks(locks)
        self.booking_state.set_locked_slot(None)

    def load_bookings(self):
        try:
            if not os.path.exists(self.bookings_file):
                return []

            with open(self.bookings_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return []
                return json.loads(content)
        except Exception:
            logger.exception("Error loading bookings")
            return []

    def save_booking(self, booking_data):
        try:

            os.makedirs(os.path.dirname(self.bookings_file), exist_ok=True)

            try:
                with open(self.bookings_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        bookings = json.loads(content)
                    else:
                        bookings = []
            except (json.JSONDecodeError, FileNotFoundError):
                logger.warning("Corrupted bookings file, creating new one")
                bookings = []

            bookings.append(booking_data)

            with open(self.bookings_file, 'w', encoding='utf-8') as f:
                json.dump(bookings, f, indent=2, ensure_ascii=False)

        except Exception:
            logger.exception("Critical error saving booking")
            raise

    def _find_booking_by_id(self, booking_id: str) -> Optional[Dict[str, Any]]:
        """Find booking by ID (full or partial)"""
        bookings = self._get_user_bookings()
        for booking in bookings:
            if booking.get('id', '').startswith(booking_id):
                return booking
        return None

    def start_booking(self):
        if not self.all_bookable:
            return BotReply(
                text=self.response_handler.get_response(
                    "no_services_available"),
                meta={"intent": "book_service", "stage": "empty"}
            )

        self.booking_state.start_booking()

        self.booking_admin.cancel_management()

        self._update_session_state({
            "booking_flow": self.session["booking_flow"],
            "state": OrderState.BOOKING,
            "in_ordering_flow": False,
            "in_cart_editing": False
        })

        return self.prompt_current_step()

    def cancel_booking(self) -> BotReply:
        self.booking_state.cancel_booking()
        self._update_session_state({
            "booking_flow": self.session["booking_flow"],
            "state": OrderState.IDLE
        })
        return BotReply(
            text=self.response_handler.get_response("booking_canceled"),
            meta={"intent": "book_service", "stage": "canceled", "tool_completed": True}
        )

    def _send_booking_notification(self, booking_data: dict):
        try:
            from notification_system.service import get_notification_service

            service = get_notification_service()
            service.send_booking_created_sync(self.business_name, booking_data)

        except Exception:
            logger.exception("Failed to send booking notification")

    def _send_booking_cancellation_notification(self, booking_data: dict):
        try:
            from notification_system.service import get_notification_service

            service = get_notification_service()
            service.send_booking_cancelled_sync(self.business_name, booking_data)

        except Exception:
            logger.exception("Failed to send booking cancellation notification")

    def restart_booking(self) -> BotReply:
        self.release_slot()
        self.booking_state.start_booking()
        return self.prompt_current_step()

    def handle_service_selection(self, message: str):
        selection = None
        available = self.all_bookable

        for s in available:
            if s.get("name", "").lower() == message.lower():
                selection = s
                break

        if not selection and message.isdigit():
            idx = int(message) - 1
            if 0 <= idx < len(available):
                selection = available[idx]

        if not selection:

            if available:
                service_list = "\n".join(
                    [f"{idx+1}. {s.get('name', 'Unknown')}"
                     for idx, s in enumerate(available)]
                )
                response_text = self._get_safe_formatted_response(
                    "invalid_service_selection",
                    user_input=message,
                    max_number=len(available),
                    service_list=service_list
                )
            else:
                response_text = self.response_handler.get_response(
                    "no_services_available")

            return BotReply(
                text=response_text,
                meta={"intent": "book_service", "stage": "invalid_selection"}
            )

        self.booking_state.update_booking_data({
            "service_name": selection.get("name"),
            "source": selection.get("source"),
            "duration_minutes": selection.get("duration_minutes"),
            "price": selection.get("price")
        })

        self.booking_state.set_state(
            self.next_step(BookingState.SERVICE_SELECTION))

        self._update_session_state({
            "booking_flow": self.session["booking_flow"]
        })

        return self.prompt_current_step()

    def handle_datetime_selection(self, message: str):
        try:
            dt_naive = datetime.strptime(message, "%Y-%m-%d %H:%M")
            dt_local = self.timezone.localize(dt_naive)
            dt_utc = dt_local.astimezone(pytz.UTC)

            current_time_utc = datetime.now(pytz.UTC)
            if dt_utc < current_time_utc:
                return BotReply(
                    text=self.response_handler.get_response("past_date_error"),
                    meta={"intent": "book_service", "stage": "invalid_time"}
                )

            is_valid, error_type, error_details = self._validate_business_hours(dt_utc)
            if not is_valid:

                hours_display = self._get_business_hours_display()

                if error_type == "closed_day":
                    response_key = "business_hours_closed_day"
                    day_name = error_details.capitalize()
                    response_text = self._get_safe_formatted_response(
                        response_key,
                        day_name=day_name,
                        business_hours=hours_display
                    )
                else:
                    response_key = "business_hours_outside_hours"
                    response_text = self._get_safe_formatted_response(
                        response_key,
                        business_hours=hours_display
                    )

                return BotReply(
                    text=response_text,
                    meta={"intent": "book_service", "stage": "invalid_time"}
                )

            original_datetime_input = message

            extra_key = None
            current_booking = self.booking_state.get_booking_data()

            current_category = self.get_current_category()
            if current_category == "restaurant":
                extra_key = current_booking.get("party_size")
            elif current_category == "consultant":
                extra_key = current_booking.get("topic")

            lock_reply = self.lock_slot(
                current_booking["service_name"], dt_utc, extra_key)
            if lock_reply:
                return lock_reply

            self.booking_state.update_booking_data({
                "datetime": dt_utc.isoformat(),
                "datetime_display": original_datetime_input
            })

            self.booking_state.set_state(
                self.next_step(BookingState.DATETIME_SELECTION))

            self._update_session_state({
                "booking_flow": self.session["booking_flow"]
            })

            return self.prompt_current_step()

        except ValueError:
            # Release locked slot on datetime error
            self.release_slot()
            return BotReply(
                text=self.response_handler.get_response("invalid_time_format"),
                meta={"intent": "book_service", "stage": "invalid_time"}
            )

    def _validate_business_hours(self, booking_time: datetime) -> tuple[bool, str, str]:
        """
        Validate booking time against business hours from config
        Returns: (is_valid, error_type, details)
        - error_type: "closed_day", "outside_hours", "valid"
        - details: day name or empty string
        """
        try:

            hours = self.business_config.get("business_hours", {})
            if not hours:
                return True, "valid", ""

            days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            day_key = days[booking_time.weekday()]

            day_slots = hours.get(day_key)
            if not day_slots:
                return False, "closed_day", day_key

            booking_local = booking_time.astimezone(self.timezone)
            booking_time_only = booking_local.time()

            for slot in day_slots:
                open_str = slot.get("open")
                close_str = slot.get("close")

                if open_str and close_str:
                    try:
                        open_time = datetime.strptime(open_str, "%H:%M").time()
                        close_time = datetime.strptime(close_str, "%H:%M").time()

                        if open_time <= booking_time_only <= close_time:
                            return True, "valid", ""
                    except ValueError:
                        continue

            return False, "outside_hours", day_key

        except Exception:
            logger.exception("Business hours validation error")
            return True, "valid", ""

    def _get_business_hours_display(self) -> str:
        hours = self.business_config.get("business_hours", {})
        if not hours:
            return "Business hours not configured."

        days_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        lines = []
        for day_key, day_name in zip(days_order, day_names):
            day_slots = hours.get(day_key)
            if day_slots:
                slot_strs = []
                for slot in day_slots:
                    open_time = slot.get("open", "??:??")
                    close_time = slot.get("close", "??:??")
                    slot_strs.append(f"{open_time}-{close_time}")
                lines.append(f"**{day_name}:** {', '.join(slot_strs)}")
            else:
                lines.append(f"**{day_name}:** Closed")

        return "\n".join(lines)

    def handle_name_collection(self, message: str):
        self.booking_state.update_booking_data({
            "customer_name": message
        })

        self.booking_state.set_state(
            self.next_step(BookingState.NAME_COLLECTION))

        self._update_session_state({
            "booking_flow": self.session["booking_flow"]
        })

        return self.prompt_current_step()

    def handle_party_size(self, message: str) -> BotReply:
        try:
            party_size = int(message.strip())

            if party_size <= 0:
                return BotReply(
                    text="Please enter a positive number for party size.",
                    meta={"intent": "book_service",
                          "stage": "invalid_party_size"}
                )

            if party_size > 20:
                return BotReply(
                    text="For parties larger than 20, please contact us directly.",
                    meta={"intent": "book_service",
                          "stage": "party_size_too_large"}
                )

            self.booking_state.update_booking_data({
                "party_size": party_size
            })

            self.booking_state.set_state(
                self.next_step(BookingState.PARTY_SIZE)
            )

            self._update_session_state({
                "booking_flow": self.session["booking_flow"]
            })

            return self.prompt_current_step()

        except ValueError:
            return BotReply(
                text="Please enter a valid number for party size (e.g., 2, 4, 6).",
                meta={"intent": "book_service", "stage": "invalid_party_size"}
            )

    def handle_topic(self, message: str) -> BotReply:
        topic = message.strip()

        if not topic or len(topic) < 3:
            return BotReply(
                text="Please provide a topic for your consultation (at least 3 characters).",
                meta={"intent": "book_service", "stage": "invalid_topic"}
            )

        self.booking_state.update_booking_data({
            "topic": topic
        })

        self.booking_state.set_state(
            self.next_step(BookingState.TOPIC)
        )

        self._update_session_state({
            "booking_flow": self.session["booking_flow"]
        })

        return self.prompt_current_step()

    def handle_special_requests(self, message: str):
        special_requests_value = "None" if message.lower() in [
            "none", "skip", "no"] else message

        self.booking_state.update_booking_data({
            "special_requests": special_requests_value
        })

        self.booking_state.set_state(
            self.next_step(BookingState.SPECIAL_REQUESTS))

        self._update_session_state({
            "booking_flow": self.session["booking_flow"]
        })

        return self.prompt_current_step()

    def handle_confirmation(self, message: str) -> BotReply:
        msg_lower = message.lower()

        if msg_lower in ["no", "n", "cancel", "stop"]:
            return self.cancel_booking()

        if msg_lower in ["yes", "y", "confirm", "thanks", "thank you", "ok", "confirmed"]:
            booking_data = self.booking_state.complete_booking()

            self.booking_admin.cancel_management()

            booking_data.update({
                "id": str(uuid.uuid4()),
                "user_session": self.session.get("session_id", "unknown"),
                "business": self.business_name,
                "status": "confirmed",
                "created_at": datetime.utcnow().isoformat()
            })

            try:
                self.save_booking(booking_data)
                self._update_session_state({
                    "state": OrderState.IDLE,
                    "booking_management": self.session["booking_management"]
                })

                self._send_booking_notification(booking_data)

                display_time = booking_data.get(
                    "datetime_display", booking_data["datetime"])
                # Use display time, not UTC
                confirmed_text = self._get_safe_formatted_response(
                    "booking_confirmed",
                    service_name=booking_data["service_name"],
                    datetime=display_time,
                    party_size=booking_data.get("party_size", "N/A")
                )

                return BotReply(
                    text=confirmed_text,
                    meta={"intent": "book_service", "stage": "confirmed",
                          "booking_id": booking_data["id"], "tool_completed": True}
                )

            except Exception:
                logger.exception("Error saving booking")
                self.booking_state.cancel_booking()
                self._update_session_state({
                    "state": OrderState.IDLE
                })

                return BotReply(
                    text="I encountered an error while saving your booking. Please try again.",
                    meta={"intent": "book_service", "stage": "error"}
                )

        return BotReply(
            text=self.response_handler.get_response("fallback_confirmation"),
            meta={"intent": "book_service", "stage": "invalid_confirmation"}
        )

    def next_step(self, current_state: BookingState) -> BookingState:
        flow = self.get_current_flow()
        try:
            idx = flow.index(current_state)
            next_state = flow[idx + 1]

            return next_state
        except (ValueError, IndexError):

            return BookingState.CONFIRMATION

    def go_back_step(self) -> BotReply:
        current_state = self.booking_state.get_state()
        flow = self.get_current_flow()

        try:
            current_index = flow.index(current_state)
            if current_index > 0:
                self.booking_state.set_state(flow[current_index - 1])
                self._clear_current_step_data(current_state)
                return self.prompt_current_step()
        except (ValueError, IndexError):
            pass

        return BotReply(
            text=self.response_handler.get_response("cannot_go_back"),
            meta={"intent": "book_service", "stage": "cannot_go_back"}
        )

    def prompt_current_step(self):
        step = self.booking_state.get_state()
        current_booking = self.booking_state.get_booking_data()

        if step == BookingState.PARTY_SIZE:
            response_text = self.response_handler.get_response(
                "enter_party_size")

            if not response_text or response_text.strip() == "":
                response_text = "👥 **How many people will be joining?**"
            return BotReply(
                text=response_text,
                meta={"intent": "book_service", "stage": "awaiting_party_size"}
            )

        elif step == BookingState.TOPIC:
            response_text = self.response_handler.get_response("enter_topic")

            if not response_text or response_text.strip() == "":
                response_text = "💬 **What would you like to discuss in your consultation?**"
            return BotReply(
                text=response_text,
                meta={"intent": "book_service", "stage": "awaiting_topic"}
            )

        elif step == BookingState.SERVICE_SELECTION:
            service_list = "\n".join(
                [f"{idx+1}. {s.get('name', 'Unknown')} (${s.get('price', 'N/A')})"
                 for idx, s in enumerate(self.all_bookable)]
            )

            response_text = self._get_safe_formatted_response(
                "select_service_prompt", menu=service_list)
            return BotReply(
                text=response_text,
                meta={"intent": "book_service", "stage": "select_service"}
            )

        elif step == BookingState.DATETIME_SELECTION:
            response_text = self.response_handler.get_response(
                "enter_datetime")
            return BotReply(
                text=response_text,
                meta={"intent": "book_service", "stage": "awaiting_datetime"}
            )

        elif step == BookingState.NAME_COLLECTION:
            response_text = self.response_handler.get_response("enter_name")

            if not response_text or response_text.strip() == "":
                response_text = "📝 **Please provide your name for the booking:**"

            return BotReply(
                text=response_text,
                meta={"intent": "book_service", "stage": "awaiting_name"}
            )

        elif step == BookingState.SPECIAL_REQUESTS:
            response_text = self.response_handler.get_response(
                "enter_special_requests")
            return BotReply(
                text=response_text,
                meta={"intent": "book_service",
                      "stage": "awaiting_special_requests"}
            )

        elif step == BookingState.CONFIRMATION:
            service_name = current_booking.get("service_name", "Unknown")
            datetime_display = current_booking.get(
                "datetime_display", current_booking.get("datetime", "Unknown"))
            customer_name = current_booking.get(
                "customer_name", "Not provided")
            party_size = current_booking.get(
                "party_size", "N/A")
            special_requests = current_booking.get("special_requests")

            special_requests_line = ""
            if special_requests and special_requests.lower() != "none":
                special_requests_line = f"**Special Requests:** {special_requests}\n"

            response_text = self._get_safe_formatted_response(
                "confirm_booking_prompt",
                service_name=service_name,
                datetime=datetime_display,
                customer_name=customer_name,
                party_size=party_size,
                special_requests_line=special_requests_line
            )

            return BotReply(
                text=response_text,
                meta={"intent": "book_service",
                      "stage": "awaiting_confirmation"}
            )

        else:
            logger.warning("Unhandled booking state: %s", step)
            return BotReply(
                text="Please continue with your booking. What would you like to do next?",
                meta={"intent": "book_service", "stage": "unknown_state"}
            )

    def _clear_current_step_data(self, current_state: BookingState):
        clearing_map = {
            BookingState.PARTY_SIZE: "party_size",
            BookingState.TOPIC: "topic",
            BookingState.DATETIME_SELECTION: "datetime",
            BookingState.NAME_COLLECTION: "customer_name",
            BookingState.SPECIAL_REQUESTS: "special_requests"
        }
        if current_state in clearing_map:
            current_booking = self.booking_state.get_booking_data()
            if clearing_map[current_state] in current_booking:
                del current_booking[clearing_map[current_state]]
        if current_state == BookingState.DATETIME_SELECTION:
            self.release_slot()

    def _handle_special_commands(self, message: str) -> Optional[BotReply]:
        msg_lower = message.lower().strip()

        command_map = {
            'cancel': self.cancel_booking,
            'exit': self.cancel_booking,
            'quit': self.cancel_booking,
            'help': self._handle_help_command,
            'back': self.go_back_step,
            'previous': self.go_back_step,
            'restart': self.restart_booking,
            'start over': self.restart_booking,
            'show services': self._handle_show_services,
            'show options': self._handle_show_services,
            'show booking': self.show_current_booking,
            'show details': self.show_current_booking,
            'review': self.show_current_booking,
            'my bookings': self.booking_admin.show_all_bookings,
            'view bookings': self.booking_admin.show_all_bookings,
            'bookings': self.booking_admin.show_all_bookings,
            'cancel bookings': self.booking_admin.show_cancellation_prompt,
            'cancel booking': self.booking_admin.show_cancellation_prompt,
            'delete booking': self.booking_admin.show_cancellation_prompt,
            'emergency exit': self.emergency_exit,
            'emergency': self.emergency_exit,
            'panic': self.emergency_exit
        }

        handler = command_map.get(msg_lower)
        if handler:
            return handler()
        return None

    def _handle_help_command(self) -> BotReply:
        return BotReply(
            text=self.response_handler.get_response("booking_help"),
            meta={"intent": "book_service", "stage": "help"}
        )

    def _handle_show_services(self) -> BotReply:
        if self.booking_state.get_state() == BookingState.SERVICE_SELECTION:
            return self.prompt_current_step()
        else:

            return self.restart_booking()

    def handle_message(self, message: str) -> BotReply:

        message_clean = message.strip().lower()

        command_reply = self._handle_special_commands(message)
        if command_reply:
            return command_reply

        if self.booking_state.is_active():

            current_state = self.booking_state.get_state()
            if current_state == BookingState.SERVICE_SELECTION:
                return self.handle_service_selection(message)
            elif current_state == BookingState.PARTY_SIZE:
                return self.handle_party_size(message)
            elif current_state == BookingState.TOPIC:
                return self.handle_topic(message)
            elif current_state == BookingState.DATETIME_SELECTION:
                return self.handle_datetime_selection(message)
            elif current_state == BookingState.NAME_COLLECTION:
                return self.handle_name_collection(message)
            elif current_state == BookingState.SPECIAL_REQUESTS:
                return self.handle_special_requests(message)
            elif current_state == BookingState.CONFIRMATION:
                return self.handle_confirmation(message)
            else:
                logger.warning("Unknown booking state: %s", current_state)
                return self._get_context_aware_fallback()

        management_reply = self.booking_admin.handle_message(message)
        if management_reply:
            return management_reply

        if not self.booking_state.is_active():

            booking_keywords = ["book", "reserve",
                                "booking", "appointment", "schedule"]
            if not any(keyword in message_clean for keyword in booking_keywords):

                return BotReply(
                    text=self.response_handler.get_response("general_fallback"),
                    meta={"intent": "fallback", "tool_completed": True}
                )

            return self.start_booking()

        return self._get_context_aware_fallback()

    def show_current_booking(self) -> BotReply:
        current_booking = self.booking_state.get_booking_data()

        service_name = current_booking.get("service_name", "Not selected")
        datetime_str = current_booking.get(
            "datetime_display", current_booking.get("datetime", "Not selected"))
        customer_name = current_booking.get("customer_name", "Not provided")
        special_requests = current_booking.get("special_requests", "")

        special_requests_line = f"**Special Requests:** {special_requests}" if special_requests else "**Special Requests:** None"

        current_state = self.booking_state.get_state()
        next_step_instruction = self._get_next_step_instruction(current_state)

        response_text = self._get_safe_formatted_response(
            "show_booking",
            service_name=service_name,
            datetime=datetime_str,
            customer_name=customer_name,
            special_requests_line=special_requests_line,
            next_step_instruction=next_step_instruction
        )

        return BotReply(
            text=response_text,
            meta={"intent": "book_service", "stage": "show_booking"}
        )

    def emergency_exit(self) -> BotReply:
        """Emergency exit from booking flow - clears all state"""
        self.booking_state.cancel_booking()
        self.booking_admin.cancel_management()
        self._update_session_state({
            "state": OrderState.IDLE
        })
        response_text = self.response_handler.get_response("emergency_exit")
        return BotReply(
            text=response_text,
            meta={"intent": "book_service", "stage": "emergency_exit"}
        )

    def _get_safe_formatted_response(self, key: str, **kwargs) -> str:
        try:
            response = self.response_handler.get_response(key, **kwargs)
            if not response:
                return f"Please continue with your booking."

            defaults = {
                'service_name': 'your service',
                'datetime': 'the scheduled time',
                'customer_name': 'customer',
                'party_size': 'N/A',
                'special_requests_line': '',
                'contact_phone': 'our support line',
                'contact_email': 'our email',
                'business_name': self.business_name,
                'menu': 'available options',
                'user_input': 'your input',
                'max_number': 'available options',
                'summary': 'your cart items',
                'items': 'cart items',
                'item': 'item',
                'qty': 'quantity',
                'next_step_instruction': 'continue with the booking',
                'bookings_list': 'your bookings',
                'current_step_instruction': 'continue with the current step'
            }
            all_kwargs = {**defaults, **kwargs}

            try:
                return response.format(**all_kwargs)
            except KeyError as e:
                logger.warning("Missing placeholder: %s, using unformatted", e)
                return response
        except Exception as e:
            logger.warning("Error getting response: %s", e)
            return f"Please continue with your booking."

    def _get_next_step_instruction(self, current_state: BookingState) -> str:
        instructions = {
            BookingState.SERVICE_SELECTION: "Select a service from the list above",
            BookingState.DATETIME_SELECTION: "Enter your preferred date and time",
            BookingState.NAME_COLLECTION: "Enter your name",
            BookingState.SPECIAL_REQUESTS: "Enter any special requests or type 'none'",
            BookingState.CONFIRMATION: "Confirm your booking with 'yes' or 'no'"
        }
        return instructions.get(current_state, "Continue with the booking process")

    def _get_context_aware_fallback(self) -> BotReply:
        current_state = self.booking_state.get_state()

        fallback_mapping = {
            BookingState.SERVICE_SELECTION: "fallback_service_selection",
            BookingState.PARTY_SIZE: "fallback_party_size",
            BookingState.TOPIC: "fallback_topic",
            BookingState.DATETIME_SELECTION: "fallback_datetime_selection",
            BookingState.NAME_COLLECTION: "fallback_name_collection",
            BookingState.SPECIAL_REQUESTS: "fallback_special_requests",
            BookingState.CONFIRMATION: "fallback_confirmation"
        }

        fallback_key = fallback_mapping.get(current_state, "general_fallback")

        try:
            response_text = self.response_handler.get_response(fallback_key)
        except Exception:
            logger.exception("Fallback response error")
            response_text = self.response_handler.get_response(
                "general_fallback")

        return BotReply(
            text=response_text,
            meta={"intent": "book_service", "stage": "fallback"}
        )

    def _get_user_bookings(self) -> List[Dict[str, Any]]:
        try:
            bookings = self.load_bookings()
            current_session_id = self.session.get("session_id", "unknown")
            return [b for b in bookings if b.get("user_session") == current_session_id]
        except Exception:
            logger.exception("Error loading bookings")
            return []

    def get_current_category(self) -> str:

        if hasattr(self, 'force_category') and self.force_category:
            return self.force_category

        self.business_config = self._load_business_config()
        return self.business_config.get("business_category", "salon")

    def get_current_flow(self) -> list:
        category = self.get_current_category()
        return CATEGORY_BOOKING_FLOW.get(category, CATEGORY_BOOKING_FLOW["salon"])
