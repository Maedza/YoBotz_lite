from typing import Any, Dict

class BotReply:
    def __init__(self, text: str, meta: Dict[str, Any] = None):
        self.text = text
        self.content = text
        self.meta = meta or {}
