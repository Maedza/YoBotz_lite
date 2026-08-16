import logging
from typing import Optional
from smart_engine.core.utils.response_channel import BotReply
from smart_engine.core.response_handler import ResponseHandler
from smart_engine.features.ordering.ordering_intent_handler import OrderingIntentHandler
from smart_engine.features.ordering.ordering_manager import OrderingManager
from smart_engine.features.ordering.ordering_enums import OrderState
from smart_engine.features.booking.booking_manager import BookingManager
from smart_engine.core.feature_toggle import get_feature_toggle
from smart_engine.core.session_manager import SessionManager

logger = logging.getLogger(__name__)

GLOBAL_EXIT_COMMANDS = {"quit", "exit", "stop", "cancel order", "main menu"}


class IntentRouter:
    def __init__(self, business_name: str, session_manager: Optional[SessionManager] = None):
        self.business_name = business_name
        self.ordering_handler = OrderingIntentHandler(business_name, session_manager)
        self.feature_toggle = get_feature_toggle(business_name)
        self.session_manager = session_manager
        logger.debug("IntentRouter initialized for '%s'", business_name)

    def _reload_feature_toggle(self):
        self.feature_toggle = get_feature_toggle(self.business_name, reload=True)

    def _create_booking_manager(self, session: dict, response_handler: ResponseHandler) -> BookingManager:
        force_category = session.get("business_category")
        return BookingManager(
            business_name=self.business_name,
            session=session,
            response_handler=response_handler,
            session_manager=self.session_manager,
            force_category=force_category
        )

    def _handle_global_exit(self, session: dict) -> BotReply:
        """Clean up all session state on exit."""
        session.pop("active_tool", None)
        session.update({
            "ordering_state": OrderState.IDLE.value,
            "ordering_sub_state": OrderState.IDLE.value,
            "ordering_cart": [],
            "in_ordering_flow": False,
            "in_cart_editing": False,
            "suspended_ordering_state": None,
            "suspended_ordering_sub_state": None,
            "suspended_ordering_cart": None,
            "suspended_at": None,
            "booking_flow": {"active": False},
            "booking_management": {"active": False},
        })

        if self.session_manager and session.get("session_id"):
            try:
                parts = session["session_id"].split('_')
                if len(parts) >= 3:
                    user_id = '_'.join(parts[:-1])
                    business_name = parts[-1]
                    self.session_manager.update_session(user_id, business_name, {
                        "active_tool": None,
                        "ordering_state": OrderState.IDLE.value,
                        "ordering_cart": [],
                        "in_ordering_flow": False,
                        "suspended_ordering_state": None,
                        "suspended_ordering_cart": None,
                        "suspended_at": None,
                    })
            except Exception as e:
                logger.error("Error persisting exit cleanup: %s", e)

        return BotReply("✅ Exited all flows. You can start fresh now!", meta={"intent": "exit"})

    def route_intent(self, intent: str, message: str, session: dict,
                     response_handler: ResponseHandler, product_handler=None,
                     cart_manager: Optional[any] = None) -> BotReply:
        """Simplified router - only acts as entry gate, tools manage their own workflows."""
        msg_lower = message.lower().strip()
        logger.debug("Routing: '%s' | '%s'", intent, message)

        self._reload_feature_toggle()


        active_tool = session.get("active_tool")
        if active_tool == "ordering":
            result = self.ordering_handler.handle_intent(intent, message, session, response_handler)
            if result:
                if result.meta.get("tool_completed"):
                    session.pop("active_tool", None)
                return result

            logger.info("[ROUTER] ordering tool active but returned None for '%s', staying in tool", message[:60])
            return BotReply(self.ordering_handler.get_fallback_response(session, response_handler),
                          meta={"intent": "ordering_active", "active_tool": "ordering"})

        if active_tool == "booking":
            bm = self._create_booking_manager(session, response_handler)
            result = bm.handle_message(message)
            if result:
                if result.meta.get("tool_completed"):
                    session.pop("active_tool", None)
                return result

            logger.info("[ROUTER] booking tool active but returned None for '%s', staying in tool", message[:60])
            return BotReply("I didn't understand that. Please respond with a valid option for your current booking session.",
                          meta={"intent": "booking_active", "active_tool": "booking"})


        if msg_lower in GLOBAL_EXIT_COMMANDS:
            return self._handle_global_exit(session)


        if intent in ('thanks', 'goodbye', 'greeting'):
            for key in (f"intent_{intent}", intent):
                try:
                    text = response_handler.get_response(key)
                    if text and text.strip():
                        return BotReply(text, meta={"intent": intent})
                except Exception:
                    pass


        template_intents = {'business_hours', 'location', 'contact', 'about', 'faq',
                            'human_check', 'help', 'feedback', 'suggestion', 'complaint'}
        if intent in template_intents:
            for key in (f"intent_{intent}", intent):
                try:
                    text = response_handler.get_response(key)
                    if text and text.strip() and text != f"[{key}] response missing":
                        return BotReply(text, meta={"intent": intent})
                except Exception:
                    pass


        is_booking = intent.startswith("book_") or intent == "book_service"
        is_management = intent == "manage_booking"
        msg_keywords = msg_lower.split()
        is_booking = is_booking or any(k in msg_keywords for k in ['book', 'booking', 'reserve', 'appointment'])
        is_management = is_management or any(k in msg_keywords for k in [
            'my bookings', 'view bookings', 'show bookings', 'cancel bookings',
            'my appointments', 'list bookings', 'booking history', 'my reservations'])

        if is_booking or is_management:
            if not self.feature_toggle.is_booking_enabled():
                return BotReply(self.feature_toggle.get_system_message("booking"), meta={"intent": "booking_disabled"})

            viewing_cmds = {"my bookings", "view bookings", "show bookings", "bookings", "list bookings"}
            if is_management and msg_lower not in viewing_cmds:
                session["active_tool"] = "booking"
                self._persist_tool_state(session)
            elif is_booking:
                session["active_tool"] = "booking"
                self._persist_tool_state(session)

            bm = self._create_booking_manager(session, response_handler)
            return bm.handle_message(message)


        if not self.feature_toggle.is_ordering_enabled():
            return BotReply(self.feature_toggle.get_system_message("ordering"), meta={"intent": "ordering_disabled"})


        if intent == "fallback" and message.strip().isdigit():
            n = int(message.strip())
            if 1 <= n <= 5:
                session["active_tool"] = "ordering"
                om = OrderingManager(self.business_name, session, response_handler)
                result = om.handle_message(message)

                self._persist_tool_state(session)
                return result


        ordering_reply = self.ordering_handler.handle_intent(intent, message, session, response_handler)
        if ordering_reply:
            if session.get("ordering_state") == OrderState.ORDERING.value:
                session["active_tool"] = "ordering"

                self._persist_tool_state(session)
            return ordering_reply


        if msg_lower in ('help', 'h', '?') or msg_lower.startswith('help '):
            help_text = response_handler.get_response("intent_help")
            if help_text and help_text.strip() and help_text != "[intent_help] response missing":
                return BotReply(help_text, meta={"intent": "help"})

        fallback_text = response_handler.get_response("intent_fallback")
        if not fallback_text or "response missing" in fallback_text:
            fallback_text = "Hello! How can I help you today?"
        return BotReply(fallback_text, meta={"intent": "fallback"})

    def get_session_stats(self) -> dict:
        if self.session_manager:
            return self.session_manager.get_session_stats()
        return {"session_manager": "not_available"}

    def force_session_cleanup(self, user_id: str = None):
        if self.session_manager:
            self.session_manager.clear_all_sessions()

    def _persist_tool_state(self, session: dict):
        """Persist active_tool state to SessionManager."""
        if not self.session_manager or not session.get("session_id"):
            return
        try:
            parts = session["session_id"].split('_')
            if len(parts) < 3:
                return
            user_id = '_'.join(parts[:-1])
            business_name = parts[-1]
            self.session_manager.update_session(user_id, business_name, {
                "active_tool": session.get("active_tool")
            })
            logger.debug("Persisted active_tool=%s for %s", session.get('active_tool'), session['session_id'])
        except Exception as e:
            logger.error("Error persisting tool state: %s", e)
