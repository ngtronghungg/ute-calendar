"""
Schedule & Calendar Feed Cache Helper
Per-user isolated caching to guarantee zero cross-student data leakage.
Every schedule and exam record MUST be strictly associated with a valid MSSV.
"""

import os
import json
import re
import secrets
import threading
from typing import List, Optional
from src.schedule_parser import CalendarEvent
from src import storage
from src.branding import DATA_TTL_SECONDS

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE_DATA_DIR = os.environ.get("DATA_DIR", "/tmp/data" if os.environ.get("VERCEL") else os.path.join(PROJECT_ROOT, "data"))
CACHE_LOCK = threading.RLock()

MSSV_REGEX = re.compile(r"^[0-9A-Za-z]{5,15}$")


def validate_mssv(mssv: Optional[str]) -> bool:
    """Validate that MSSV contains strictly 5 to 15 alphanumeric characters."""
    if not mssv or not isinstance(mssv, str):
        return False
    return bool(MSSV_REGEX.fullmatch(mssv.strip()))


def _get_user_file_paths(mssv: str):
    """Determine cache file paths for a specific validated MSSV."""
    safe_mssv = str(mssv).strip()
    user_dir = os.path.join(BASE_DATA_DIR, "users", safe_mssv)
    try:
        os.makedirs(user_dir, exist_ok=True)
    except Exception:
        pass
    return (
        os.path.join(user_dir, "calendar_feed_cache.json"),
        os.path.join(user_dir, "exam_cache.json"),
    )


def save_cached_exams(exams: List[CalendarEvent], mssv: Optional[str] = None) -> None:
    """Permanently persist parsed exam CalendarEvent objects to storage and disk for a specific MSSV."""
    if not exams or not mssv or not validate_mssv(mssv):
        return
    safe_mssv = str(mssv).strip()
    with CACHE_LOCK:
        try:
            existing = {e.uid: e for e in load_cached_exams(mssv=safe_mssv)}
            for ex in exams:
                existing[ex.uid] = ex
            storage_key = f"exam_cache:{safe_mssv}"
            storage.set_json(storage_key, [e.to_dict() for e in existing.values()], ttl=DATA_TTL_SECONDS)

            _, exam_file = _get_user_file_paths(safe_mssv)
            os.makedirs(os.path.dirname(exam_file), exist_ok=True)
            tmp_file = f"{exam_file}.tmp.{secrets.token_hex(4)}"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in existing.values()], f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, exam_file)
        except Exception:
            try:
                if 'tmp_file' in locals() and os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except Exception:
                pass


def load_cached_exams(mssv: Optional[str] = None) -> List[CalendarEvent]:
    """Load cached exam CalendarEvent objects strictly for a validated MSSV. Returns [] if mssv is missing or invalid."""
    if not mssv or not validate_mssv(mssv):
        return []
    safe_mssv = str(mssv).strip()
    with CACHE_LOCK:
        storage_key = f"exam_cache:{safe_mssv}"
        stored = storage.get_json(storage_key)
        if stored and isinstance(stored, list):
            try:
                return [CalendarEvent.from_dict(d) for d in stored]
            except Exception:
                pass

        _, exam_file = _get_user_file_paths(safe_mssv)
        if os.path.exists(exam_file):
            try:
                with open(exam_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                return [CalendarEvent.from_dict(d) for d in raw]
            except Exception:
                pass

        return []


def save_feed_cache(events: List[CalendarEvent], mssv: Optional[str] = None) -> None:
    """Cache parsed CalendarEvent objects strictly for a validated MSSV."""
    if not events or not mssv or not validate_mssv(mssv):
        return
    safe_mssv = str(mssv).strip()
    with CACHE_LOCK:
        try:
            old_events = load_feed_cache(mssv=safe_mssv)
            merged = {e.uid: e for e in old_events}
            for e in events:
                merged[e.uid] = e
            storage_key = f"feed_cache:{safe_mssv}"
            storage.set_json(storage_key, [e.to_dict() for e in merged.values()], ttl=DATA_TTL_SECONDS)

            feed_file, _ = _get_user_file_paths(safe_mssv)
            os.makedirs(os.path.dirname(feed_file), exist_ok=True)
            tmp_file = f"{feed_file}.tmp.{secrets.token_hex(4)}"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in merged.values()], f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, feed_file)
        except Exception:
            try:
                if 'tmp_file' in locals() and os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except Exception:
                pass


def load_feed_cache(mssv: Optional[str] = None) -> List[CalendarEvent]:
    """Load cached CalendarEvent objects strictly for a validated MSSV. Returns [] if mssv is missing or invalid."""
    if not mssv or not validate_mssv(mssv):
        return []
    safe_mssv = str(mssv).strip()
    with CACHE_LOCK:
        storage_key = f"feed_cache:{safe_mssv}"
        stored = storage.get_json(storage_key)
        events = []
        if stored and isinstance(stored, list):
            try:
                events = [CalendarEvent.from_dict(d) for d in stored]
            except Exception:
                events = []

        if not events:
            feed_file, _ = _get_user_file_paths(safe_mssv)
            if os.path.exists(feed_file):
                try:
                    with open(feed_file, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    events = [CalendarEvent.from_dict(d) for d in raw]
                except Exception:
                    pass

        cached_exams = load_cached_exams(mssv=safe_mssv)

    existing_uids = {e.uid for e in events}
    for ex in cached_exams:
        if ex.uid not in existing_uids:
            events.append(ex)
    return events
