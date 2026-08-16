#!/usr/bin/env python3
"""
Recovery script for orphaned onboarding sessions.
Run AFTER server restart to restore sessions from disk.
Usage: python3 recover_session.py <session_id> <business_name>
"""
import sys
import json
from pathlib import Path

SESSION_DIR = Path(__file__).parent / "data" / "onboarding_sessions"

def recover_session(session_id: str, business_name: str, step_data: dict = None):
    session_file = SESSION_DIR / f"session_{session_id}.json"
    if session_file.exists():
        print(f"Session {session_id} already has a disk file")
        d = json.loads(session_file.read_text())
        print(f"  business_name: {d.get('business_name')}")
        print(f"  current_step: {d.get('current_step')}")
        if not d.get("business_name"):
            d["business_name"] = business_name
            if step_data:
                d["data"].update(step_data)
            session_file.write_text(json.dumps(d, indent=2))
            print(f"  -> Updated with business_name='{business_name}'")
        return


    d = {
        "session_id": session_id,
        "created_at": 0,
        "current_step": 1,
        "completed": False,
        "business_name": business_name,
        "data": step_data or {"name": business_name},
    }
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    session_file.write_text(json.dumps(d, indent=2))
    print(f"Created session file: {session_file}")
    print(f"  business_name: {business_name}")
    print(f"Restart the server to load this session.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 recover_session.py <session_id> <business_name>")
        print("Example: python3 recover_session.py 13cc1136 yo_inn")
        sys.exit(1)

    session_id = sys.argv[1]
    business_name = sys.argv[2].lower().replace(" ", "_")
    recover_session(session_id, business_name)
