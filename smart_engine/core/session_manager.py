import os
import threading
from datetime import datetime, timedelta
from typing import Dict, Any
import json
import logging

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, persistence_file: str = None):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.persistence_file = persistence_file
        self.lock = threading.RLock()
        self.cleanup_interval = timedelta(hours=1)
        self.last_cleanup = datetime.now()

        if persistence_file and os.path.exists(persistence_file):
            self._load_sessions()

    def _load_sessions(self):
        """Load sessions from persistence file."""
        with self.lock:
            try:
                with open(self.persistence_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                loaded = 0
                for key, session_data in data.items():
                    try:

                        for ts_field in ('created_at', 'last_accessed'):
                            if ts_field in session_data and isinstance(session_data[ts_field], str):
                                session_data[ts_field] = datetime.fromisoformat(session_data[ts_field])
                        self.sessions[key] = session_data
                        loaded += 1
                    except Exception as e:
                        logger.error("Error loading session %s: %s", key, e)

                logger.debug("Loaded %s/%s sessions", loaded, len(data))

            except json.JSONDecodeError as e:
                logger.error("JSON error in %s: %s", self.persistence_file, e)
                backup = f"{self.persistence_file}.corrupted.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                try:
                    os.rename(self.persistence_file, backup)
                except Exception:
                    pass

            except Exception as e:
                logger.error("Error loading sessions: %s", e)

    def _make_serializable(self, obj):
        """Recursively convert non-serializable objects for JSON."""
        from enum import Enum
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, Enum):
            return obj.value
        elif isinstance(obj, dict):
            return {kk: self._make_serializable(vv) for kk, vv in obj.items()}
        elif isinstance(obj, list):
            return [self._make_serializable(vv) for vv in obj]
        elif isinstance(obj, (set, tuple)):
            return list(obj)
        return obj

    def _save_sessions(self):
        """Save sessions to persistence file."""
        if not self.persistence_file:
            return

        with self.lock:
            try:
                serializable = self._make_serializable(dict(self.sessions))


                temp_file = f"{self.persistence_file}.tmp"
                dir_path = os.path.dirname(self.persistence_file) or '.'
                os.makedirs(dir_path, exist_ok=True)

                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(serializable, f, indent=2, ensure_ascii=False)

                import shutil
                if os.path.exists(self.persistence_file):
                    shutil.move(self.persistence_file, f"{self.persistence_file}.backup")
                shutil.move(temp_file, self.persistence_file)

            except Exception as e:
                logger.error("Error saving sessions: %s", e)

    def get_session(self, user_id: str, business_name: str) -> Dict[str, Any]:
        """Get or create session for user+business."""
        key = f"{user_id}_{business_name}"
        now = datetime.now()

        with self.lock:

            if now - self.last_cleanup > self.cleanup_interval or len(self.sessions) > 1000:
                self._cleanup_sessions()
                self.last_cleanup = now

            if key not in self.sessions:
                self.sessions[key] = {
                    "session_id": key,
                    "user_id": user_id,
                    "business_name": business_name,
                    "created_at": now,
                    "last_accessed": now,
                    "cart": [],
                    "metadata": {},
                    "in_ordering_flow": False,
                    "in_cart_editing": False,
                    "booking_flow": {"active": False},
                    "booking_management": {"active": False},
                }
                logger.debug("Created new session: %s", key)
                self._save_sessions()
            else:
                self.sessions[key]["last_accessed"] = now

            return self.sessions[key]

    def update_session(self, user_id: str, business_name: str, updates: Dict[str, Any]):
        """Update session data."""
        key = f"{user_id}_{business_name}"
        with self.lock:
            if key in self.sessions:
                from enum import Enum
                for k, v in updates.items():
                    if isinstance(v, Enum):
                        self.sessions[key][k] = v.value
                    elif isinstance(v, dict) and k in self.sessions[key] and isinstance(self.sessions[key][k], dict):
                        self.sessions[key][k].update(v)
                    else:
                        self.sessions[key][k] = v
                self.sessions[key]["last_accessed"] = datetime.now()

                important_keys = [k for k in updates if k != "last_accessed"]
                if important_keys:
                    self._save_sessions()
                    logger.debug("Updated %s: %s", key, important_keys)
            else:
                logger.debug("Session not found: %s", key)

    def persist_session(self, session: Dict[str, Any]):
        """Force persist a session."""
        if not session or "session_id" not in session:
            return
        key = session["session_id"]
        with self.lock:
            if key in self.sessions:
                self.sessions[key].update(session)
                self._save_sessions()

    def _cleanup_sessions(self):
        """Remove expired sessions."""
        now = datetime.now()
        expired = 0
        for key, session in list(self.sessions.items()):
            try:
                inactive = now - session.get("last_accessed", now)
                age = now - session.get("created_at", now)
                if (inactive > timedelta(hours=2) and age > timedelta(hours=1)) or age > timedelta(hours=24):
                    del self.sessions[key]
                    expired += 1
            except Exception:
                del self.sessions[key]
                expired += 1

        if expired > 0:
            logger.debug("Cleaned up %s sessions", expired)
            self._save_sessions()

    def delete_session(self, user_id: str, business_name: str) -> bool:
        key = f"{user_id}_{business_name}"
        with self.lock:
            if key in self.sessions:
                del self.sessions[key]
                self._save_sessions()
                return True
            return False

    def clear_all_sessions(self):
        with self.lock:
            self.sessions.clear()
            self._save_sessions()

    def get_session_count(self) -> int:
        with self.lock:
            return len(self.sessions)

    def get_active_sessions(self, max_inactive_minutes: int = 5) -> list:
        cutoff = datetime.now() - timedelta(minutes=max_inactive_minutes)
        with self.lock:
            return [s.copy() for s in self.sessions.values() if s.get("last_accessed", datetime.now()) > cutoff]

    def get_session_stats(self) -> Dict[str, Any]:
        now = datetime.now()
        with self.lock:
            active = sum(1 for s in self.sessions.values() if now - s.get("last_accessed", now) < timedelta(minutes=5))
            return {
                "total_sessions": len(self.sessions),
                "active_sessions": active,
                "last_cleanup": self.last_cleanup.isoformat(),
                "persistence_file": self.persistence_file
            }

    def get_user_sessions(self, user_id: str) -> Dict[str, Dict[str, Any]]:
        """Get all sessions for a given user across businesses."""
        with self.lock:
            return {
                key: sess for key, sess in self.sessions.items()
                if sess.get("user_id") == user_id
            }

    def __contains__(self, key: str) -> bool:
        return key in self.sessions

    def __len__(self) -> int:
        return len(self.sessions)

    def keys(self):
        return list(self.sessions.keys())

    def values(self):
        return [s.copy() for s in self.sessions.values()]

    def items(self):
        return [(k, v.copy()) for k, v in self.sessions.items()]
