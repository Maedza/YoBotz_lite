import logging
from typing import Optional
from smart_engine.core.utils.response_channel import BotReply
from smart_engine.core.response_handler import ResponseHandler
from smart_engine.features.ordering.ordering_manager import OrderingManager, OrderState

logger = logging.getLogger(__name__)


class OrderingIntentHandler:

    def __init__(self, business_name: str, session_manager=None):
        self.business_name = business_name
        self.session_manager = session_manager

    def handle_intent(self, intent: str, message: str, session: dict,
                    response_handler: ResponseHandler) -> Optional[BotReply]:
        msg_lower = message.lower().strip()

        ordering_manager = OrderingManager(
            self.business_name, session, response_handler
        )

        session_ordering_state_raw = session.get("ordering_state")

        if session_ordering_state_raw is None or session_ordering_state_raw != OrderState.ORDERING.value:
            if intent.startswith("place_order") or intent == "product_search" or msg_lower in ["buy", "order", "menu"]:
                result = ordering_manager.start_ordering()

                if intent == "product_search":
                    result = ordering_manager.handle_message(message)

                self._persist_ordering_state(session)
                return result

            if msg_lower in ["cart", "view cart", "show cart"]:
                return BotReply(ordering_manager.get_cart_summary())

            return None

        result = ordering_manager.handle_message(message)

        self._persist_ordering_state(session)

        return result

    def get_fallback_response(self, session: dict, response_handler) -> str:
        sub_state = session.get("ordering_sub_state")
        prompt = "I didn't understand that. "
        if sub_state == "awaiting_category_selection":
            prompt += "Please choose a category by typing its name or number."
        elif sub_state == "awaiting_product_selection":
            prompt += "Please select a product by typing its name or number."
        elif sub_state == "awaiting_quantity":
            prompt += "Please enter a number for the quantity."
        elif sub_state == "awaiting_delivery_option":
            prompt += "Please choose: 'pickup' or 'delivery'."
        else:
            prompt += response_handler.get_response("intent_fallback") or "How can I help you?"
        return prompt

    def _persist_ordering_state(self, session: dict):
        if not self.session_manager:
            return

        if not session.get("session_id"):
            return

        try:
            parts = session["session_id"].split('_')
            if len(parts) < 3:
                return

            user_id = '_'.join(parts[:-1])
            business_name = parts[-1]

            updates = {}
            ordering_keys = ['ordering_state', 'ordering_sub_state',
                           'ordering_cart', 'ordering_product_list',
                           'awaiting_quit_confirmation', 'active_tool']

            for key in ordering_keys:
                if key in session:
                    updates[key] = session[key]

            if updates:
                self.session_manager.update_session(user_id, business_name, updates)
        except Exception as e:
            logger.exception(f"[OrderingIntentHandler] Error persisting ordering state: {e}")
