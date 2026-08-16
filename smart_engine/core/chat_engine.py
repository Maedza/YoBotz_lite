import os
import yaml
import logging
from smart_engine.core.utils.model_handler import IntentModelHandler
from smart_engine.core.session_manager import SessionManager
from smart_engine.core.intent_router import IntentRouter
from smart_engine.core.response_handler import ResponseHandler
from smart_engine.core.utils.response_channel import BotReply
from smart_engine.features.ordering.product_handler import ProductHandler

import pprint
pp = pprint.PrettyPrinter(indent=2)

logger = logging.getLogger(__name__)


class AttrDict(dict):
    """Allow dot-access to dictionary keys"""
    def __getattr__(self, name):
        try:
            value = self[name]
            if isinstance(value, dict):
                return AttrDict(value)
            return value
        except KeyError:
            raise AttributeError(f"No such attribute: {name}")


class ChatEngine:
    """Main chatbot engine for a business instance."""

    def __init__(self, business_name: str):
        self.business_name = business_name
        self.business_config = self.load_business_config()


        os.makedirs("data/sessions", exist_ok=True)
        self.session_manager = SessionManager(persistence_file=f"data/sessions/sessions_{business_name}.json")


        self.intent_router = IntentRouter(
            business_name=business_name,
            session_manager=self.session_manager
        )

        self.responses = ResponseHandler(business_name)
        self.product_handler = ProductHandler(business_name)


        MODEL_REPO = self.business_config.model.path if "model" in self.business_config else "mock"
        HF_TOKEN = os.getenv("HF_TOKEN")

        logger.info("Loading model for %s: %s", business_name, MODEL_REPO)
        self.model_handler = IntentModelHandler(MODEL_REPO, token=HF_TOKEN, use_mock=False)
        if self.model_handler.use_mock:
            logger.warning("ChatEngine[%s]: model unavailable, using mock fallback", business_name)

        logger.info("ChatEngine initialized for %s", business_name)


    def load_business_config(self):
        path = os.path.join("businesses", self.business_name, "business_config.yaml")
        if not os.path.exists(path):
            logger.warning("business_config.yaml not found for '%s', using defaults", self.business_name)
            return AttrDict({})
        with open(path, "r", encoding="utf-8") as f:
            return AttrDict(yaml.safe_load(f) or {})


    def process_message(self, message: str, user_id: str) -> BotReply:
        """Handles user input, runs model prediction, and routes responses."""

        session = self.session_manager.get_session(user_id, self.business_name)

        try:
            active_tool = session.get("active_tool")
            if active_tool:
                logger.info("[MODEL] SKIP — active_tool=%s", active_tool)
                intent = "fallback"
                confidence = 1.0
            else:
                logger.info("[MODEL] CALL — predicting intent for message: '%s'", message[:80])
                intent, confidence, _ = self.model_handler.predict_intent(message)
                logger.info("[MODEL] RESULT — intent='%s' confidence=%.2f", intent, confidence)


            reply = self.intent_router.route_intent(
                intent,
                message,
                session,
                self.responses,
                product_handler=self.product_handler,
            )


            reply.meta.update({
                "intent": intent, 
                "confidence": confidence,
                "active_tool": active_tool
            })

        except Exception as e:
            logger.error("Error in ChatEngine.process_message: %s", e)
            import traceback
            logger.error("Traceback: %s", traceback.format_exc())
            reply = BotReply(self.responses.get_response("error_fallback"), meta={"intent": "error"})


        try:
            self.session_manager.update_session(user_id, self.business_name, {})
        except Exception as e:
            logger.warning("Session update warning: %s", e)

        logger.debug("Message processed: '%s' | Intent: '%s' | Confidence: %s", 
                    message, reply.meta.get('intent'), reply.meta.get('confidence'))

        return reply


    def get_session_stats(self) -> dict:
        """Get session statistics for monitoring"""
        stats = self.session_manager.get_session_stats()
        stats["business_name"] = self.business_name
        return stats


    def cleanup_user_sessions(self, user_id: str):
        """Clean up all sessions for a specific user"""
        user_sessions = self.session_manager.get_user_sessions(user_id)
        for business_name in user_sessions.keys():
            self.session_manager.delete_session(user_id, business_name)
        logger.debug("Cleaned up sessions for user: %s", user_id)


    def force_cleanup_all_sessions(self):
        """Force cleanup of all sessions"""
        self.session_manager.clear_all_sessions()
        logger.debug("Force cleaned all sessions for %s", self.business_name)
