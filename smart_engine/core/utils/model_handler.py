import json
import os
import logging

logger = logging.getLogger(__name__)


class IntentModelHandler:
    """
    Handles intent prediction using:
      - Hugging Face model (if torch is installed)
      - Local model directory
      - Mock fallback (offline/demo)
    Always returns: (top_intent, confidence, top_labels)
    """

    def __init__(self, model_path_or_repo="mock", token=None, use_mock=False):
        self.use_mock = use_mock or (model_path_or_repo == "mock")
        self.device = None
        self.model = None
        self.tokenizer = None
        self.id2label = {}

        if not self.use_mock:
            try:
                import torch
                from transformers import AutoTokenizer, AutoModelForSequenceClassification

                self.device = torch.device(
                    "cuda" if torch.cuda.is_available() else "cpu")


                if os.path.isdir(model_path_or_repo):
                    self.tokenizer = AutoTokenizer.from_pretrained(model_path_or_repo)
                    self.model = AutoModelForSequenceClassification.from_pretrained(
                        model_path_or_repo).to(self.device)
                    id2label_path = os.path.join(model_path_or_repo, "id2label.json")
                    if not os.path.exists(id2label_path):
                        raise FileNotFoundError(f"id2label.json missing in {model_path_or_repo}")
                    with open(id2label_path, "r", encoding="utf-8") as f:
                        self.id2label = json.load(f)


                else:
                    # Import here to avoid import errors if huggingface_hub is not installed
                    from huggingface_hub import hf_hub_download

                    self.tokenizer = AutoTokenizer.from_pretrained(model_path_or_repo, use_auth_token=token)
                    self.model = AutoModelForSequenceClassification.from_pretrained(
                        model_path_or_repo, use_auth_token=token).to(self.device)
                    try:
                        file_path = hf_hub_download(
                            repo_id=model_path_or_repo,
                            filename="id2label.json",
                            token=token,
                        )
                        with open(file_path, "r", encoding="utf-8") as f:
                            self.id2label = json.load(f)
                    except Exception:
                        raise ValueError("id2label.json could not be loaded from Hugging Face Hub")

            except Exception as e:

                logger.warning("Model load failed: %s. Falling back to mock mode.", e)
                self.use_mock = True

    def predict_intent(self, text, top_k=3):
        """Predict top intent labels for a given text input."""
        logger.debug(f"🤖 MODEL CALLED for text: '{text[:50]}...' | mode: {'MOCK' if self.use_mock else 'REAL'}")

        if self.use_mock:
            result = self._mock_predict(text, top_k)
            logger.debug(f"🤖 Mock prediction: '{result[0]}' (confidence: {result[1]})")
            return result

        import torch
        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, padding=True).to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
        probs = torch.nn.functional.softmax(outputs.logits, dim=1)
        top_probs, top_indices = torch.topk(probs, k=top_k, dim=1)
        labels = [self.id2label.get(str(i.item()), "fallback") for i in top_indices[0]]

        logger.debug(f"🤖 Real model prediction: '{labels[0]}' (confidence: {top_probs[0][0].item():.4f})")
        return labels[0], round(top_probs[0][0].item(), 4), labels


    def _mock_predict(self, text, top_k=3):
        """Offline/demo mock intents"""
        text_lower = text.lower()
        labels = []


        if any(w in text_lower for w in ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]):
            labels.append("greeting")


        if any(w in text_lower for w in ["thanks", "thank you", "thx"]):
            labels.append("thanks")


        if any(w in text_lower for w in ["bye", "goodbye", "see you", "later"]):
            labels.append("goodbye")


        if any(w in text_lower for w in ["hours", "open", "close", "business hours", "opening", "closing", "when are you open", "what time"]):
            labels.append("business_hours")


        if any(w in text_lower for w in ["order", "menu", "buy", "bread", "cake", "pastry", "show", "view", "products"]):
            labels.append("place_order")


        if text_lower.startswith("search ") or text_lower.startswith("find "):
            labels.append("product_search")


        if any(w in text_lower for w in ["my bookings", "view bookings", "show bookings", "bookings list",
                                           "cancel booking", "delete booking", "manage bookings"]):
            labels.append("manage_booking")


        if any(w in text_lower for w in ["book", "booking", "reserve", "reservation", "appointment", "schedule", "table"]):
            labels.append("book_table")


        if any(w in text_lower for w in ["where", "location", "address", "find", "directions", "map", "store"]):
            labels.append("location")


        if any(w in text_lower for w in ["human", "bot", "robot", "ai", "artificial", "real person", "are you real", 
                                        "who am i talking to", "is this a bot", "are you ai", "chatbot", "actual person"]):
            labels.append("human_check")


        if any(w in text_lower for w in ["contact", "phone", "call", "email", "number", "reach", "get in touch", 
                                        "customer service", "support line"]):
            labels.append("contact")


        if any(w in text_lower for w in ["faq", "frequently asked", "common questions", "questions", 
                                        "what if", "policy", "policies", "information"]):
            labels.append("faq")


        if any(w in text_lower for w in ["about", "story", "who are you", "background", "history", "tell me about"]):
            labels.append("about")


        if not labels:
            labels.append("fallback")


        while len(labels) < top_k:
            labels.append("fallback")

        return labels[0], 0.95, labels[:top_k]
