#!/usr/bin/env python3
"""Forget only this plugin's session copy; never the original Hermes transcript."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from observational.store import MemoryStore


def forget(home, session_id, confirmed=False):
    home = Path(home).expanduser().absolute()
    if any(p.is_symlink() for p in (home, *home.parents)) or not home.is_dir():
        raise ValueError("Unsafe profile path")
    if not isinstance(session_id, str) or not session_id or len(session_id) > 512:
        raise ValueError("Invalid session identity")
    home = home.resolve(strict=True)
    profile_key = hashlib.sha256(str(home).encode()).hexdigest()
    database = home / "observational-memory" / (hashlib.sha256(session_id.encode()).hexdigest() + ".sqlite3")
    if not database.is_file() or database.is_symlink():
        raise ValueError("No plugin memory exists for that exact session")
    if not confirmed:
        return {"would_forget_plugin_session": True, "original_hermes_history_affected": False, "changed": False}
    store = MemoryStore(database, profile_key, session_id)
    try:
        store.forget()
        state = store.read()
        if not state["disabled"] or state["sources"] or state["observations"]:
            raise RuntimeError("Forgetting readback failed")
        return {"changed": True, "disabled_tombstone": True, "source_count": 0, "observation_count": 0, "original_hermes_history_affected": False, "provider_retention_or_backups_erased": False}
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--confirm-plugin-copy-deletion", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(forget(args.home, args.session_id, args.confirm_plugin_copy_deletion), indent=2))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "confirmed_deleted": False}))
        raise SystemExit(1)
