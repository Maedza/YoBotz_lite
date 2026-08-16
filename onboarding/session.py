"""
Onboarding session management — in-memory state, persisted to disk on each update.
"""

import uuid
import time
import json
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


_SESSIONS_DIR = Path(__file__).parent.parent / "data" / "onboarding_sessions"
_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _session_file(session_id: str) -> Path:
    return _SESSIONS_DIR / f"session_{session_id}.json"


@dataclass
class OnboardingSession:
    """Represents a single onboarding flow."""
    session_id: str
    created_at: float = field(default_factory=time.time)
    current_step: int = 1
    data: dict = field(default_factory=dict)
    completed: bool = False
    business_name: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "current_step": self.current_step,
            "completed": self.completed,
            "business_name": self.business_name,
            "data": self.data,
        }

    def save(self):
        """Persist session to disk."""
        _session_file(self.session_id).write_text(
            json.dumps(self.to_dict()), encoding="utf-8"
        )

    @classmethod
    def load(cls, session_id: str) -> Optional["OnboardingSession"]:
        """Load session from disk."""
        path = _session_file(session_id)
        if not path.exists():
            return None
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                session_id=d["session_id"],
                created_at=d.get("created_at", time.time()),
                current_step=d.get("current_step", 1),
                data=d.get("data", {}),
                completed=d.get("completed", False),
                business_name=d.get("business_name"),
            )
        except Exception:
            return None


class SessionManager:
    """Manages onboarding sessions — loaded from disk on init, persisted on each change."""

    def __init__(self):
        self._sessions: dict[str, OnboardingSession] = {}
        self._load_all()

    def _load_all(self):
        """Load any persisted sessions from disk."""
        for path in _SESSIONS_DIR.glob("session_*.json"):
            try:
                session_id = path.stem.replace("session_", "")
                session = OnboardingSession.load(session_id)
                if session and not session.completed:
                    self._sessions[session.session_id] = session
            except Exception:
                pass

    def create(self) -> OnboardingSession:
        """Create a new onboarding session."""
        session = OnboardingSession(session_id=str(uuid.uuid4())[:8])
        self._sessions[session.session_id] = session
        session.save()
        return session

    def get(self, session_id: str) -> Optional[OnboardingSession]:
        """Get a session by ID (memory first, then disk)."""
        if session_id in self._sessions:
            return self._sessions[session_id]

        session = OnboardingSession.load(session_id)
        if session:
            self._sessions[session_id] = session
        return session

    def update(self, session_id: str, step_data: dict) -> bool:
        """Update session with step data. Persists to disk."""
        session = self.get(session_id)
        if not session:
            return False

        session.data.update(step_data)
        session.save()
        return True

    def advance(self, session_id: str) -> bool:
        """Advance to next step. Persists to disk."""
        session = self.get(session_id)
        if not session:
            return False

        session.current_step += 1
        session.save()
        return True

    def complete(self, session_id: str) -> bool:
        """Mark session as completed and persist."""
        session = self.get(session_id)
        if not session:
            return False

        session.completed = True
        session.save()
        return True

    def delete(self, session_id: str) -> bool:
        """Delete a session from memory and disk."""
        if session_id in self._sessions:
            del self._sessions[session_id]
        path = _session_file(session_id)
        if path.exists():
            path.unlink()
        return True

    def cleanup_expired(self, max_age_seconds: int = 3600):
        """Remove expired sessions from memory and disk."""
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if (now - s.created_at) > max_age_seconds and not s.completed
        ]
        for sid in expired:
            self.delete(sid)


_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager
