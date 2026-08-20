import re
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

from smart_engine.core.utils.response_channel import BotReply
from smart_engine.core.response_handler import ResponseHandler
from smart_engine.features.ordering.product_handler import ProductHandler, SMART_DISPLAY_LIMIT
from smart_engine.features.ordering.reservation_time_validator import ReservationTimeValidator

from .ordering_enums import OrderState, OrderSubState

logger = logging.getLogger(__name__)

class OrderingManager:
    """
    Main ordering manager - handles everything in one place
    Follows the same pattern as BookingManager
    Supports both ordering and reservation modes
    """

    def __init__(self, business_name: str, session: dict, response_handler: ResponseHandler):
        self.business_name = business_name
        self.session = session
        self.response_handler = response_handler

        self._ensure_state()

        self.product_handler = ProductHandler(business_name)

        self.business_config = self._load_business_config()

        self.reservation_validator = ReservationTimeValidator(business_name, self.business_config)

        self.reservation_mode = self._is_reservation_mode_enabled()

        self.EDIT_COMMANDS = {"edit", "edit cart"}
        self.CONFIRM_COMMANDS = {"confirm", "yes"}
        self.CANCEL_COMMANDS = {"cancel", "cancel order", "no"}

    def _load_business_config(self) -> Dict[str, Any]:
        try:
            from core.business_loader import load_business_config
            config = load_business_config(self.business_name)
            if config:
                logger.info(f"[OrderingManager] Loaded business config for {self.business_name}")
                return config
        except Exception as e:
            logger.warning(f"[OrderingManager] Could not load business config: {e}")
        return {}

    def _is_reservation_mode_enabled(self) -> bool:
        try:
            from core.business_loader import load_business_config
            config = load_business_config(self.business_name)
            if config and config.get('features', {}).get('enable_reservation_mode', False):
                logger.info(f"[OrderingManager] Reservation mode enabled for {self.business_name}")
                return True
        except Exception as e:
            logger.warning(f"[OrderingManager] Could not check reservation mode: {e}")
        return False

    def _ensure_state(self):
        if "ordering_state" not in self.session:
            self.session["ordering_state"] = OrderState.IDLE.value
            self.session["ordering_sub_state"] = OrderSubState.NONE.value
            self.session["ordering_cart"] = []
            self.session["ordering_product_list"] = []

        if "awaiting_quit_confirmation" not in self.session:
            self.session["awaiting_quit_confirmation"] = False

    @property
    def state(self) -> OrderState:
        value = self.session.get("ordering_state", OrderState.IDLE.value)
        try:
            state_enum = OrderState(value)
            return state_enum
        except ValueError:
            return OrderState.IDLE

    @state.setter
    def state(self, new_state: OrderState):
        self.session["ordering_state"] = new_state.value
        if new_state != OrderState.ORDERING:
            self.session["ordering_sub_state"] = OrderSubState.NONE.value

    @property
    def sub_state(self) -> OrderSubState:
        value = self.session.get("ordering_sub_state", OrderSubState.NONE.value)
        try:
            sub_state_enum = OrderSubState(value)
            return sub_state_enum
        except ValueError:
            return OrderSubState.NONE

    @sub_state.setter
    def sub_state(self, new_sub_state: OrderSubState):
        self.session["ordering_sub_state"] = new_sub_state.value

    def is_active(self) -> bool:
        active = self.state == OrderState.ORDERING
        return active

    def start_ordering(self) -> BotReply:
        """Start new ordering flow - FLOW: Category → Product → Add More/Edit/Cancel/Confirm"""

        if self.is_active():
            return self._show_current_state()

        self.state = OrderState.ORDERING
        self.sub_state = OrderSubState.AWAITING_CATEGORY_SELECTION

        # Only load ALL products if we don't have filtered products already
        # Prevents overwriting category-filtered products when flow restarts
        if not self.session.get("ordering_product_list"):
            products = self.product_handler.get_products()
            self.session["ordering_product_list"] = products

        if "ordering_cart" not in self.session:
            self.session["ordering_cart"] = []

        logger.info(f"[OrderingManager] Ordering started")
        logger.debug(
            f"[OrderingManager] Session keys: {[k for k in self.session.keys() if 'order' in k.lower()]}")

        return self._show_category_menu()

    def get_available_days(self, days_ahead: int = 7) -> list:
        return self.reservation_validator.get_available_days(days_ahead)

    def handle_time_input(self, time_str: str, date_str: str) -> Tuple[bool, str]:
        selected_day = self.session.get('reservation_selected_day', {})
        if not selected_day:
            return False, "No day selected. Please go back and select a day."

        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        except:
            return False, "Invalid date. Please go back and select a day again."

        is_valid, message = self.reservation_validator.is_time_within_hours(date_obj, time_str)

        if not is_valid:
            return False, message

        parsed_time = self.reservation_validator.parse_time_input(time_str)

        reservation_datetime = date_obj.replace(
            hour=parsed_time.hour,
            minute=parsed_time.minute,
            second=0,
            microsecond=0
        )

        is_valid, message = self.reservation_validator.validate_reservation_time(reservation_datetime)

        if not is_valid:
            return False, message

        self.session['reservation_datetime'] = reservation_datetime.isoformat()

        return True, ""

    def cancel_order(self) -> BotReply:
        self.cart = []

        self.session.pop("reservation_datetime", None)

        self.session.pop("ordering_selected_product", None)
        self.session.pop("ordering_selected_quantity", None)

        self.state = OrderState.IDLE
        self.sub_state = OrderSubState.NONE

        self.session["awaiting_quit_confirmation"] = False

        return BotReply(
            self.response_handler.get_response("order_canceled"),
            meta={"tool_completed": True}
        )

    @property
    def cart(self) -> list:
        cart = self.session.get("ordering_cart", [])
        return cart

    @cart.setter
    def cart(self, new_cart: list):
        self.session["ordering_cart"] = new_cart

    def is_cart_empty(self) -> bool:
        empty = len(self.cart) == 0
        return empty

    def add_to_cart(self, product: Dict[str, Any], quantity: int = 1, variant: Optional[Dict[str, Any]] = None) -> str:
        """Add item to cart — returns status message.

        If variant is provided, the cart stores variant name + price
        and the item name becomes 'Product Name (Variant Name)' so
        different variants of the same product are separate cart items.
        """

        cart = self.cart.copy()
        item_name = product["name"]
        item_price = product.get("price", 0.0)

        if variant:
            item_name = f"{product['name']} ({variant['name']})"
            item_price = variant.get("price", item_price)

        for item in cart:
            if item.get("name") == item_name:
                item["quantity"] = item.get("quantity", 0) + quantity
                self.cart = cart
                return f"Added {quantity} more of {item_name}."

        cart_item = {
            "name": item_name,
            "price": item_price,
            "quantity": quantity,
        }
        if variant:
            cart_item["variant"] = variant["name"]
        cart.append(cart_item)
        self.cart = cart

        return f"Added {quantity} x {item_name} to cart."

    def remove_from_cart(self, target: str) -> Optional[str]:
        cart = self.cart.copy()

        if target.isdigit():
            idx = int(target) - 1
            if 0 <= idx < len(cart):
                removed = cart.pop(idx)
                self.cart = cart
                return removed.get("name")

        target_lower = target.lower()
        for i, item in enumerate(cart):
            if target_lower in item.get("name", "").lower():
                removed = cart.pop(i)
                self.cart = cart
                return removed.get("name")

        return None

    def change_quantity(self, target: str, new_qty: int) -> Optional[str]:
        cart = self.cart.copy()

        if target.isdigit():
            idx = int(target) - 1
            if 0 <= idx < len(cart):
                if new_qty <= 0:
                    removed = cart.pop(idx)
                    self.cart = cart
                    return removed.get("name")
                cart[idx]["quantity"] = new_qty
                self.cart = cart
                return cart[idx].get("name")

        target_lower = target.lower()
        for i, item in enumerate(cart):
            if target_lower in item.get("name", "").lower():
                if new_qty <= 0:
                    removed = cart.pop(i)
                    self.cart = cart
                    return removed.get("name")
                cart[i]["quantity"] = new_qty
                self.cart = cart
                return cart[i].get("name")

        return None

    def get_cart_summary(self) -> str:
        if self.is_cart_empty():
            return self.response_handler.get_response("cart_empty")

        lines = []
        total = 0.0
        for item in self.cart:
            qty = item.get("quantity", 0)
            price = item.get("price", 0.0)
            subtotal = price * qty
            total += subtotal
            lines.append(f"- {qty} x {item.get('name', '?')} → ${subtotal:.2f}")

        lines.append(f"**Total: ${total:.2f}**")
        return "\n".join(lines)

    def handle_message(self, message: str) -> BotReply:
        msg = message.strip()
        msg_lower = msg.lower()

        try:
            if msg_lower.startswith("search ") or msg_lower.startswith("find "):
                query = msg.split(" ", 1)[1] if " " in msg else ""
                return self._handle_search_command(query)

            if msg_lower in ["quit", "exit"]:

                if not self.is_cart_empty():

                    quit_prompt = self.response_handler.get_response("quit_prompt")

                    self.session["awaiting_quit_confirmation"] = True

                    return BotReply(quit_prompt)
                else:
                    return self.cancel_order()

            if self.session.get("awaiting_quit_confirmation"):

                self.session["awaiting_quit_confirmation"] = False

                if msg_lower in ["yes", "y"]:
                    return self.cancel_order()

                elif msg_lower in ["no", "n"]:
                    quit_continue = self.response_handler.get_response("quit_continue")
                    return BotReply(f"{quit_continue}\n\n{self._show_current_state()}")

                else:
                    self.session["awaiting_quit_confirmation"] = True
                    quit_prompt = self.response_handler.get_response("quit_prompt")
                    return BotReply(quit_prompt)

            if msg_lower in ["cancel order", "stop"]:
                return self.cancel_order()

            if msg_lower in ["cart", "view cart", "show cart"]:
                return BotReply(self.get_cart_summary())

            if msg_lower in self.EDIT_COMMANDS:
                return self._enter_edit_mode()

            current_state = self.state
            current_sub_state = self.sub_state
            logger.debug(
                f"[OrderingManager] Routing based on state: {current_state.name}, sub_state: {current_sub_state.name}")

            if current_state == OrderState.IDLE and current_sub_state == OrderSubState.NONE and msg.strip().isdigit():
                number = int(msg.strip())
                if 1 <= number <= 5:

                    start_result = self.start_ordering()
                    if start_result:

                        return self._handle_category_selection(msg)
                    else:
                        return self._get_fallback_response()

            if current_sub_state == OrderSubState.AWAITING_CATEGORY_SELECTION:
                return self._handle_category_selection(msg)

            if current_sub_state == OrderSubState.AWAITING_PRODUCT_SELECTION:
                logger.debug(
                    f"[OrderingManager] → Routing to _handle_product_selection")
                return self._handle_product_selection(msg)

            if current_sub_state == OrderSubState.AWAITING_VARIANT_SELECTION:
                return self._handle_variant_selection(msg)

            elif current_sub_state == OrderSubState.AWAITING_MORE_ITEMS:
                return self._handle_more_items(msg)

            elif current_sub_state == OrderSubState.AWAITING_CONFIRMATION:
                return self._handle_confirmation(msg)

            elif current_sub_state == OrderSubState.AWAITING_RESERVATION_DATETIME:
                return self._handle_reservation_datetime(msg)

            elif current_sub_state == OrderSubState.CART_EDITING:
                return self._handle_edit_commands(msg)

            return self._get_fallback_response()

        except Exception as e:
            logger.exception(f"[OrderingManager] Error in handle_message: {e}")
            return BotReply(self.response_handler.get_response("error_fallback"))

    def _handle_category_selection(self, message: str) -> BotReply:
        msg_lower = message.lower().strip()

        logger.info(
            f"[OrderingManager] _handle_category_selection: '{message}' -> '{msg_lower}'")

        try:
            categories_dict = self.product_handler.get_categories()

            if not categories_dict:
                return BotReply(self.response_handler.get_response("no_products_available"))

            category = self._find_category(message, categories_dict)

            if category:

                products = self.product_handler.get_products_by_category(category)
                self.session["ordering_product_list"] = products

                self.sub_state = OrderSubState.AWAITING_PRODUCT_SELECTION
                logger.debug(
                    f"[OrderingManager] ✅ Category '{category}' selected, moving to AWAITING_PRODUCT_SELECTION")

                return self._show_product_menu()
            else:
                fallback = self.response_handler.get_response("category_selection_fallback")
                category_menu = self._show_category_menu()
                return BotReply(f"{fallback}\n\n{category_menu.text}")

        except Exception as e:
            logger.exception(
                f"[OrderingManager] Error in _handle_category_selection: {e}")
            return BotReply(self.response_handler.get_response("error_fallback"))

    def _handle_product_selection(self, message: str) -> BotReply:
        msg_lower = message.lower().strip()

        if msg_lower.startswith("search ") or msg_lower.startswith("find "):
            query = message.split(" ", 1)[1] if " " in message else ""
            return self._handle_search_command(query)

        command_words = ["quit", "exit", "stop", "cancel", "help"]
        menu_commands = ["menu", "show menu", "list products", "products"]
        back_commands = ["back", "categories", "main menu"]

        if msg_lower in command_words:
            fallback = self.response_handler.get_response("product_selection_fallback")
            return BotReply(f"That looks like a command, not a product.\n\n{fallback}")

        if msg_lower in menu_commands:
            return self._show_product_menu()

        if msg_lower in back_commands:
            self.sub_state = OrderSubState.AWAITING_CATEGORY_SELECTION
            return self._show_category_menu()

        if message.strip().isdigit():
            return self._handle_smart_model_selection(int(message.strip()))

        products = self.session.get("ordering_product_list", [])
        if products:
            for p in products:
                if msg_lower in p.get("name", "").lower():
                    if p.get("has_variants") and p.get("variants"):
                        self.session["ordering_selected_product"] = p
                        self.session["ordering_selected_quantity"] = 1
                        self.sub_state = OrderSubState.AWAITING_VARIANT_SELECTION
                        return self._show_variant_menu(p)
                    self.add_to_cart(p, 1)
                    self.sub_state = OrderSubState.AWAITING_MORE_ITEMS
                    more_prompt = self.response_handler.get_response("add_more_prompt")
                    return BotReply(f"✅ Added: {p['name']}\n\n{more_prompt}")

        fallback = self.response_handler.get_response("product_selection_fallback")
        return BotReply(fallback)

    def _handle_smart_model_selection(self, number: int) -> BotReply:
        smart_models = self.session.get("ordering_smart_models", [])
        if not smart_models:
            return BotReply(self.response_handler.get_response("no_products_available"))

        current_offset = self.session.get("ordering_smart_offset", 0)
        visible = smart_models[current_offset:current_offset + SMART_DISPLAY_LIMIT]

        if number == len(visible) + 1 and len(smart_models) > current_offset + len(visible):

            new_offset = current_offset + len(visible)
            self.session["ordering_smart_offset"] = new_offset
            return self._show_expanded_product_menu(new_offset)

        idx = number - 1
        if idx < 0 or idx >= len(visible):
            fallback = self.response_handler.get_response("product_selection_fallback")
            return BotReply(f"Invalid selection. {fallback}")

        model = visible[idx]
        self.session.pop("ordering_smart_offset", None)

        return self._resolve_base_model_selection(model)

    def _resolve_base_model_selection(self, model: Dict[str, Any]) -> BotReply:
        """Resolve a selected base model: one product → add, multiple → refine."""
        group = model["products"]

        if len(group) == 1:
            product = group[0]
            if product.get("has_variants") and product.get("variants"):
                self.session["ordering_selected_product"] = product
                self.session["ordering_selected_quantity"] = 1
                self.sub_state = OrderSubState.AWAITING_VARIANT_SELECTION
                return self._show_variant_menu(product)

            self.add_to_cart(product, 1)
            self.sub_state = OrderSubState.AWAITING_MORE_ITEMS
            more_prompt = self.response_handler.get_response("add_more_prompt")
            return BotReply(f"✅ Added: {product['name']}\n\n{more_prompt}")

        lines = []
        for i, p in enumerate(group):
            if p.get("has_variants") and p.get("variants"):
                min_p = min(v["price"] for v in p["variants"])
                lines.append(f"{i+1}. {p['name']} — from ${min_p:.2f} ({len(p['variants'])} variants)")
            else:
                lines.append(f"{i+1}. {p['name']} — ${p.get('price', 0):.2f}")

        self.session["ordering_product_list"] = group
        self.sub_state = OrderSubState.AWAITING_PRODUCT_SELECTION
        return BotReply(
            f"📦 **{model['base_name']}** — select:\n\n" + "\n".join(lines)
        )

    def _handle_search_command(self, query: str) -> BotReply:
        query = query.strip()
        if not query:
            return BotReply("Please type what you're looking for. Example: 'search bread'")

        if self.sub_state == OrderSubState.AWAITING_PRODUCT_SELECTION:
            products = self.session.get("ordering_product_list", [])
            category = products[0].get("category", "") if products else ""
            results = self.product_handler.search_products(query, category=category or None)
        else:
            # Category not yet selected — search across all products
            results = self.product_handler.search_products(query)

        if not results:
            fallback = self.response_handler.get_response("product_selection_fallback")
            return BotReply(f"❌ No results for '{query}'.\n\n{fallback}")

        self.session["ordering_product_list"] = results
        self.sub_state = OrderSubState.AWAITING_PRODUCT_SELECTION

        menu_lines = []
        for i, p in enumerate(results):
            if p.get("has_variants") and p.get("variants"):
                min_p = min(v["price"] for v in p["variants"])
                menu_lines.append(f"{i+1}. {p['name']} — from ${min_p:.2f} ({len(p['variants'])} variants)")
            else:
                menu_lines.append(f"{i+1}. {p['name']} — ${p.get('price', 0):.2f}")

        result_text = "\n".join(menu_lines)
        return BotReply(
            f"🔍 Results for '{query}':\n\n{result_text}\n\n"
            f"Select a number to add, or type 'back' for the full menu."
        )

    def  _handle_more_items(self, message: str) -> BotReply:
        msg_lower = message.lower().strip()

        if msg_lower in ["quit", "exit"]:

            quit_prompt = self.response_handler.get_response("quit_prompt")
            self.session["awaiting_quit_confirmation"] = True
            return BotReply(quit_prompt)

        if msg_lower in ["cancel", "cancel order", "stop"]:
            return self.cancel_order()

        if msg_lower in ["yes", "y", "more", "add more"]:
            self.sub_state = OrderSubState.AWAITING_PRODUCT_SELECTION
            return self._show_product_menu()

        if msg_lower in ["edit", "edit cart", "modify"]:
            return self._enter_edit_mode()

        if msg_lower in ["no", "n", "done", "checkout", "that's all", "that's it", "confirm"]:

            if self.is_cart_empty():
                response = self.response_handler.get_response("cart_empty")
                self.state = OrderState.IDLE
                self.sub_state = OrderSubState.NONE
            else:
                self.sub_state = OrderSubState.AWAITING_CONFIRMATION

                if self.reservation_mode:

                    self.sub_state = OrderSubState.AWAITING_RESERVATION_DATETIME

                    available_days = self.get_available_days(7)
                    datetime_prompt = self.response_handler.get_response(
                        "enter_reservation_datetime",
                        fallback="📅 **Select Pickup Day**\n\nYou can:\n• Type a number (e.g., '1', '2', '3')\n• Type a day name (e.g., 'tomorrow', 'friday')"
                    )

                    if available_days:
                        day_list = "\n".join([f"{i+1}. {d['day_display']} ({d['slots_count']} slots)" 
                                              for i, d in enumerate(available_days)])
                        return BotReply(f"{datetime_prompt}\n\n**Available Days:**\n{day_list}")
                    else:
                        return BotReply(f"{datetime_prompt}\n\n❌ No available days for reservation.")
                else:
                    cart_summary = self.get_cart_summary()
                    confirm_prompt = self.response_handler.get_response(
                        "cart_summary",
                        summary=cart_summary
                    )
                    return BotReply(confirm_prompt)

            return BotReply(response)

        if msg_lower in ["more", "add more"]:
            self.sub_state = OrderSubState.AWAITING_PRODUCT_SELECTION
            return self._show_product_menu()

        self.sub_state = OrderSubState.AWAITING_PRODUCT_SELECTION
        return self._handle_product_selection(message)

    def _handle_confirmation(self, message: str) -> BotReply:
        msg_lower = message.lower()

        if self.reservation_mode:
            if msg_lower in ["yes", "y", "confirm"]:

                reservation_datetime = self.session.get("reservation_datetime")
                datetime_display = ""

                if reservation_datetime:
                    try:
                        dt = datetime.fromisoformat(reservation_datetime)
                        datetime_display = dt.strftime("%Y-%m-%d at %H:%M")
                    except:
                        pass

                order_summary = self.get_cart_summary()

                if datetime_display:

                    timeout_minutes = self.reservation_validator.get_confirmation_timeout()

                    confirmed_msg = self.response_handler.get_response(
                        "reservation_confirmed_with_time",
                        fallback="✅ **Reservation Confirmed!**\n\n**Date & Time:** {datetime}\n**Items:**\n{summary}\n\nThank you for your reservation!",
                        datetime=datetime_display,
                        summary=order_summary,
                        timeout=timeout_minutes
                    )
                else:
                    confirmed_msg = self.response_handler.get_response(
                        "reservation_confirmed",
                        fallback="Your reservation has been confirmed!"
                    )
                    confirmed_msg = f"{confirmed_msg}\n\n{order_summary}"

                self._send_order_notification(
                    order_type="Reservation",
                    datetime_str=datetime_display
                )

                self.cart = []
                self.session.pop("reservation_datetime", None)
                self.state = OrderState.IDLE
                self.sub_state = OrderSubState.NONE

                return BotReply(
                    confirmed_msg,
                    meta={"tool_completed": True}
                )

            elif msg_lower in ["no", "n", "cancel"]:
                return self.cancel_order()

            elif msg_lower in self.EDIT_COMMANDS:
                return self._enter_edit_mode()

        else:
            if msg_lower in ["yes", "y", "confirm"]:
                order_summary = self.get_cart_summary()
                confirmed_msg = self.response_handler.get_response("order_confirmed")
                self._send_order_notification(order_type="Order")
                self.cart = []
                self.state = OrderState.IDLE
                self.sub_state = OrderSubState.NONE
                return BotReply(
                    f"{confirmed_msg}\n\n{order_summary}",
                    meta={"tool_completed": True}
                )

            elif msg_lower in ["no", "n", "cancel"]:
                return self.cancel_order()

            elif msg_lower in self.EDIT_COMMANDS:
                return self._enter_edit_mode()

        fallback = self.response_handler.get_response("confirmation_fallback")
        return BotReply(fallback)

    def _handle_reservation_datetime(self, message: str) -> BotReply:
        msg_lower = message.lower().strip()

        if msg_lower in ["cancel", "back"]:
            self.session.pop("reservation_selected_day", None)
            self.session.pop("reservation_awaiting_time", None)
            return self._enter_edit_mode()

        if self.session.get("reservation_awaiting_time"):
            return self._handle_time_input_for_free_text(message)

        available_days = self.get_available_days(7)

        if not available_days:
            error_msg = self.response_handler.get_response("invalid_reservation_datetime")
            return BotReply(f"{error_msg}\n\n❌ No available days for reservation. Please try again later.")

        success, error_msg_text, selected_date = self.reservation_validator.parse_date_input(msg_lower, 7)

        if success and selected_date:

            self.session["reservation_selected_day"] = {
                'date': selected_date,
                'day_name': selected_date.strftime('%A').lower(),
                'day_display': selected_date.strftime('%A, %b %d')
            }
            self.session["reservation_awaiting_time"] = True

            hours = self.reservation_validator.get_business_hours_for_day(selected_date)

            day_selected_prompt = self.response_handler.get_response(
                "day_selected_prompt",
                day_display=selected_date.strftime('%A, %b %d'),
                business_hours=hours
            )
            return BotReply(day_selected_prompt)

        day_list = "\n".join([f"{i+1}. {d['day_display']} ({d['slots_count']} slots)" 
                              for i, d in enumerate(available_days)])

        enter_datetime = self.response_handler.get_response("enter_reservation_datetime")
        return BotReply(
            f"{enter_datetime}\n\n**Available Days:**\n{day_list}\n\n"
            f"Or type 'back' to go back."
        )

    def _handle_time_input_for_free_text(self, time_str: str) -> BotReply:
        selected_day = self.session.get("reservation_selected_day", {})
        date_obj = selected_day.get('date')

        if not date_obj:

            self.session.pop("reservation_awaiting_time", None)
            return self._handle_reservation_datetime(time_str)

        success, message = self.handle_time_input(time_str, date_obj.strftime("%Y-%m-%d"))

        if not success:

            hours = self.reservation_validator.get_business_hours_for_day(date_obj)
            time_prompt = self.response_handler.get_response(
                "time_input_prompt",
                error_message=message,
                business_hours=hours
            )
            return BotReply(time_prompt)

        self.session.pop("reservation_awaiting_time", None)
        self.sub_state = OrderSubState.AWAITING_CONFIRMATION

        cart_summary = self.get_cart_summary()
        datetime_display = date_obj.strftime('%A, %b %d') + " at " + time_str

        full_summary = f"**Reservation Time:** {datetime_display}\n\n{cart_summary}"

        summary_text = self.response_handler.get_response(
            "cart_summary_reservation",
            fallback="Here's your reservation summary:\n{summary}\n\nConfirm your reservation?",
            summary=full_summary
        )

        return BotReply(summary_text)

    def _enter_edit_mode(self) -> BotReply:
        if self.is_cart_empty():
            return BotReply(self.response_handler.get_response("cart_empty"))

        self.sub_state = OrderSubState.CART_EDITING

        numbered_cart = self._get_numbered_cart()

        edit_prompt = self.response_handler.get_response("edit_cart_prompt", items=numbered_cart)
        return BotReply(edit_prompt)

    def _handle_edit_commands(self, message: str) -> BotReply:
        msg_lower = message.lower().strip()

        if msg_lower == "done":

            if self.reservation_mode:

                existing_datetime = self.session.get("reservation_datetime")
                if existing_datetime:

                    self.sub_state = OrderSubState.AWAITING_CONFIRMATION
                    cart_summary = self.get_cart_summary()

                    dt = datetime.fromisoformat(existing_datetime)
                    datetime_display = dt.strftime("%Y-%m-%d at %H:%M")

                    full_summary = f"**Reservation Time:** {datetime_display}\n\n{cart_summary}"

                    summary_text = self.response_handler.get_response(
                        "cart_summary_reservation",
                        fallback="Here's your reservation summary:\n{summary}\n\nConfirm your reservation?",
                        summary=full_summary
                    )
                    return BotReply(f"✅ Cart updated!\n\n{summary_text}")
                else:
                    self.sub_state = OrderSubState.AWAITING_RESERVATION_DATETIME

                    available_days = self.get_available_days(7)
                    datetime_prompt = self.response_handler.get_response(
                        "enter_reservation_datetime",
                        fallback="📅 **Select Pickup Day**\n\nYou can:\n• Type a number (e.g., '1', '2', '3')\n• Type a day name (e.g., 'tomorrow', 'friday')"
                    )

                    if available_days:
                        day_list = "\n".join([f"{i+1}. {d['day_display']} ({d['slots_count']} slots)" 
                                              for i, d in enumerate(available_days)])
                        return BotReply(f"✅ Cart updated!\n\n{datetime_prompt}\n\n**Available Days:**\n{day_list}")
                    else:
                        return BotReply(f"✅ Cart updated!\n\n{datetime_prompt}\n\n❌ No available days for reservation.")
            else:
                self.sub_state = OrderSubState.AWAITING_CONFIRMATION
                cart_summary = self.get_cart_summary()
                summary_text = self.response_handler.get_response("cart_summary", summary=cart_summary)
                return BotReply(f"✅ Cart updated!\n\n{summary_text}")

        if msg_lower == "clear" or msg_lower == "clear cart":
            self.cart = []
            self.state = OrderState.IDLE
            self.sub_state = OrderSubState.NONE
            cleared_msg = self.response_handler.get_response("cart_cleared")
            empty_msg = self.response_handler.get_response("cart_empty")
            return BotReply(f"{cleared_msg}\n\n{empty_msg}")

        response = self._parse_edit_command(msg_lower)

        if self.is_cart_empty():
            self.state = OrderState.IDLE
            self.sub_state = OrderSubState.NONE
            empty_after_edit = self.response_handler.get_response("empty_after_edit")
            return BotReply(f"{response}\n\n{empty_after_edit}")

        numbered_cart = self._get_numbered_cart()
        return BotReply(f"{response}\n\n{numbered_cart}\n\nType 'done' when finished editing.")

    def _parse_edit_command(self, command: str) -> str:
        remove_match = re.match(r"remove\s+(\d+|\w+)", command)
        if remove_match:
            target = remove_match.group(1)
            removed = self.remove_from_cart(target)
            if removed:
                return self.response_handler.get_response("item_removed", item=removed)
            return self.response_handler.get_response("item_not_found")

        change_match = re.match(r"(?:change|set)\s+(\d+|\w+)\s+(?:to|->)?\s*(\d+)", command)
        if change_match:
            target = change_match.group(1)
            new_qty = int(change_match.group(2))
            changed = self.change_quantity(target, new_qty)
            if changed:
                return self.response_handler.get_response("quantity_updated", item=changed, qty=new_qty)
            return self.response_handler.get_response("item_not_found")

        return self.response_handler.get_response("error_fallback")

    def _show_category_menu(self) -> BotReply:
        categories_dict = self.product_handler.get_categories()

        if not categories_dict:
            return BotReply(self.response_handler.get_response("no_categories_available"))

        categories = list(categories_dict.keys())

        menu_lines = [f"{i+1}. {category}" for i, category in enumerate(categories)]
        menu_text = "\n".join(menu_lines)

        category_prompt = self.response_handler.get_response(
            "category_menu_prompt",
            categories=menu_text
        )

        return BotReply(
            text=category_prompt,
            meta={"intent": "place_order", "stage": "category_selection"}
        )

    def _show_product_menu(self) -> BotReply:
        products = self.session.get("ordering_product_list", [])

        if not products:
            return BotReply(self.response_handler.get_response("no_products_available"))

        category = products[0].get("category", "") if products else ""

        smart_models = self.product_handler.get_unique_models_by_category(category)
        total_models = len(smart_models)
        show_limit = min(SMART_DISPLAY_LIMIT, total_models)
        visible = smart_models[:show_limit]
        more_count = total_models - show_limit

        self.session["ordering_smart_models"] = smart_models

        menu_lines = []
        for i, m in enumerate(visible):
            if m["min_price"] == m["max_price"]:
                price_str = f"${m['min_price']:.2f}"
            else:
                price_str = f"from ${m['min_price']:.2f}"
            variant_note = f" ({m['variant_count']} variants)" if m['variant_count'] > 1 else ""
            menu_lines.append(f"{i+1}. {m['base_name']}{variant_note} — {price_str}")

        if more_count > 0:
            menu_lines.append(f"{show_limit+1}. 🔽 Show {more_count} more models...")

        menu_text = "\n".join(menu_lines)
        search_prompt = "💡 Type 'search [model]' to find something specific"

        menu_prompt = self.response_handler.get_response(
            "product_menu_prompt", menu=menu_text
        )
        full_text = f"{menu_prompt}\n\n{search_prompt}"

        return BotReply(
            text=full_text,
            meta={"intent": "place_order", "stage": "product_selection"}
        )

    def _show_expanded_product_menu(self, offset: int = 0) -> BotReply:
        smart_models = self.session.get("ordering_smart_models", [])
        if not smart_models:
            return BotReply(self.response_handler.get_response("no_products_available"))

        batch = smart_models[offset:offset + SMART_DISPLAY_LIMIT]
        menu_lines = []
        for i, m in enumerate(batch):
            price_str = f"from ${m['min_price']:.2f}" if m['min_price'] != m['max_price'] else f"${m['min_price']:.2f}"
            variant_note = f" ({m['variant_count']} variants)" if m['variant_count'] > 1 else ""
            menu_lines.append(f"{i+1}. {m['base_name']}{variant_note} — {price_str}")

        remaining = len(smart_models) - offset - len(batch)
        if remaining > 0:
            menu_lines.append(f"{len(batch)+1}. 🔽 Show {remaining} more...")

        search_prompt = "💡 Type 'search [model]' to find something specific"
        menu_text = "\n".join(menu_lines)
        return BotReply(f"{menu_text}\n\n{search_prompt}")

    def _show_variant_menu(self, product: Dict[str, Any]) -> BotReply:
        variants = product.get("variants", [])
        lines = [f"{i+1}. {v['name']} - ${v['price']:.2f}" for i, v in enumerate(variants)]
        menu_text = "\n".join(lines)
        prompt = self.response_handler.get_response(
            "variant_selection_prompt",
            fallback="📦 **{product_name}** — select a variant:\n\n{menu}",
            product_name=product["name"],
            menu=menu_text,
        )
        return BotReply(prompt, meta={"intent": "place_order", "stage": "variant_selection"})

    def _handle_variant_selection(self, message: str) -> BotReply:
        msg_lower = message.lower().strip()
        product = self.session.get("ordering_selected_product", {})
        variants = product.get("variants", [])

        if msg_lower in ("back", "cancel"):
            self.session.pop("ordering_selected_product", None)
            self.session.pop("ordering_selected_quantity", None)
            self.sub_state = OrderSubState.AWAITING_PRODUCT_SELECTION
            return self._show_product_menu()

        if message.strip().isdigit():
            idx = int(message.strip()) - 1
            if 0 <= idx < len(variants):
                variant = variants[idx]
                quantity = self.session.pop("ordering_selected_quantity", 1)
                self.session.pop("ordering_selected_product", None)

                display_name = f"{product['name']} ({variant['name']})"
                self.add_to_cart(product, quantity, variant)

                self.sub_state = OrderSubState.AWAITING_MORE_ITEMS
                more_prompt = self.response_handler.get_response("add_more_prompt")
                return BotReply(f"✅ Added: {quantity} x {display_name}\n\n{more_prompt}")

        return self._show_variant_menu(product)

    def _show_current_state(self) -> BotReply:
        if self.sub_state == OrderSubState.AWAITING_CATEGORY_SELECTION:
            return self._show_category_menu()
        elif self.sub_state == OrderSubState.AWAITING_PRODUCT_SELECTION:
            return self._show_product_menu()
        elif self.sub_state == OrderSubState.AWAITING_VARIANT_SELECTION:
            product = self.session.get("ordering_selected_product")
            if product and product.get("variants"):
                return self._show_variant_menu(product)
            return BotReply("Something went wrong. Please start over.")
        elif self.sub_state == OrderSubState.AWAITING_MORE_ITEMS:
            cart_summary = self.get_cart_summary()
            more_prompt = self.response_handler.get_response("add_more_prompt")
            return BotReply(f"{cart_summary}\n\n{more_prompt}")
        elif self.sub_state == OrderSubState.AWAITING_CONFIRMATION:
            cart_summary = self.get_cart_summary()
            summary_text = self.response_handler.get_response("cart_summary", summary=cart_summary)
            return BotReply(summary_text)
        elif self.sub_state == OrderSubState.CART_EDITING:
            numbered_cart = self._get_numbered_cart()
            edit_prompt = self.response_handler.get_response("edit_cart_prompt", items=numbered_cart)
            return BotReply(edit_prompt)

        return BotReply(self.response_handler.get_response("current_state_fallback"))

    def _get_numbered_cart(self) -> str:
        if self.is_cart_empty():
            return "Cart is empty"

        lines = []
        for i, item in enumerate(self.cart, 1):
            subtotal = item.get("price", 0.0) * item.get("quantity", 0)
            lines.append(f"{i}. {item.get('quantity', 0)} x {item.get('name', '?')} → ${subtotal:.2f}")

        return "\n".join(lines)

    def _find_category(self, message: str, categories: dict) -> Optional[str]:
        categories_list = list(categories.keys())

        if message.isdigit():
            idx = int(message) - 1
            if 0 <= idx < len(categories_list):
                return categories_list[idx]

        message_lower = message.lower()
        for category in categories_list:
            if message_lower in category.lower():
                return category

        return None

    def _send_order_notification(self, order_type: str = "Order", datetime_str: str = ""):
        try:
            from notification_system.service import get_notification_service

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            order_id = f"{self.business_name}_{timestamp}"

            order_data = {
                "order_id": order_id,
                "customer_name": self.session.get("user_name", "Customer"),
                "total_amount": sum(item.get("price", 0) * item.get("quantity", 1) for item in self.cart),
                "items": self.cart,
                "timestamp": datetime.now().isoformat(),
                "order_type": order_type
            }

            if datetime_str:
                order_data["reservation_datetime"] = datetime_str

            service = get_notification_service()
            service.send_order_created_sync(self.business_name, order_data)

            logger.info(f"[OrderingManager] Notification sent for {order_type} {order_id}")
        except Exception as e:
            logger.error(f"[OrderingManager] Failed to send order notification: {e}")

    def _get_fallback_response(self) -> BotReply:
        fallbacks = {
            OrderSubState.AWAITING_CATEGORY_SELECTION: self.response_handler.get_response("category_selection_fallback"),
            OrderSubState.AWAITING_PRODUCT_SELECTION: self.response_handler.get_response("product_selection_fallback"),
            OrderSubState.AWAITING_VARIANT_SELECTION: "Please select a variant by typing its number, or type 'back' to return.",
            OrderSubState.AWAITING_MORE_ITEMS: self.response_handler.get_response("more_items_fallback"),
            OrderSubState.AWAITING_CONFIRMATION: self.response_handler.get_response("confirmation_fallback"),
            OrderSubState.CART_EDITING: "Use: remove [number], change [number] to [quantity], clear, or done."
        }

        response = fallbacks.get(self.sub_state, self.response_handler.get_response("fallback"))
        return BotReply(response)
