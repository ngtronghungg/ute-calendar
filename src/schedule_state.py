"""
Schedule State Management
Handles per-student manual schedule adjustments:
- Cancellations (marking specific classes as cancelled)
- Makeup classes (adding manual make-up lecture sessions)
Stored strictly isolated per MSSV in persistent storage.
"""

import hashlib
from datetime import datetime
from typing import Optional, List, Set
from src import storage
from src.schedule_parser import CalendarEvent
from src.branding import APP_NAME, DATA_TTL_SECONDS


def load_cancellations(mssv: Optional[str] = None) -> Set[str]:
    """Load manual class cancellations strictly for a specific student."""
    if not mssv:
        return set()
    return storage.smembers(f"cancelled:{mssv.strip()}")


def add_cancellation(mssv: str, uid_or_key: str) -> bool:
    """Add a manual cancellation for a specific student."""
    if not mssv or not uid_or_key:
        return False
    return storage.sadd(f"cancelled:{mssv.strip()}", str(uid_or_key).strip(), ttl=DATA_TTL_SECONDS) >= 0


def remove_cancellation(mssv: str, uid_or_key: str) -> bool:
    """Restore a previously cancelled class for a specific student."""
    if not mssv or not uid_or_key:
        return False
    return storage.srem(f"cancelled:{mssv.strip()}", str(uid_or_key).strip(), ttl=DATA_TTL_SECONDS) >= 0


def load_makeup_classes(mssv: Optional[str] = None) -> List[CalendarEvent]:
    """Load manually added make-up classes strictly for a specific student."""
    if not mssv:
        return []
    stored = storage.get_json(f"makeup:{mssv.strip()}", default=[])
    if stored and isinstance(stored, list):
        try:
            return [CalendarEvent.from_dict(d) for d in stored]
        except Exception:
            pass
    return []


def save_makeup_classes(mssv: str, events: List[CalendarEvent]) -> bool:
    """Save make-up classes for a specific student to persistent storage."""
    if not mssv:
        return False
    return storage.set_json(f"makeup:{mssv.strip()}", [e.to_dict() for e in events], ttl=DATA_TTL_SECONDS)


def add_makeup_class(
    mssv: str,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    location: str = "HCMUTE",
    note: str = ""
) -> CalendarEvent:
    """Add a new make-up class session dedicated to a specific student."""
    if not mssv:
        raise ValueError("MSSV is required to add makeup class.")
    clean_title = title.strip()
    if not clean_title.startswith("[HỌC BÙ]"):
        clean_title = f"[HỌC BÙ] {clean_title}"
    raw_sig = f"{mssv.strip()}|{clean_title}|{start_dt.isoformat()}"
    sig = hashlib.sha1(raw_sig.encode("utf-8")).hexdigest()[:12]
    uid = f"makeup-{sig}"
    desc = (
        f"LỊCH HỌC BÙ CHÍNH THỨC\n"
        f"• Môn: {clean_title}\n"
        f"• Giờ học: {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')} (Ngày {start_dt.strftime('%d/%m/%Y')})\n"
        f"• Phòng: {location}\n"
        f"• Ghi chú: {note or 'Lịch học bù do giảng viên hoặc cổng trường thông báo.'}\n"
        f"Hệ thống: {APP_NAME}"
    )
    ev = CalendarEvent(
        uid=uid,
        title=clean_title,
        start_datetime=start_dt,
        end_datetime=end_dt,
        location=location,
        description=desc,
        event_type="CLASS",
        category="HỌC BÙ",
    )
    events = load_makeup_classes(mssv)
    events = [e for e in events if e.uid != uid]
    events.append(ev)
    save_makeup_classes(mssv, events)
    return ev


def remove_makeup_class(mssv: str, uid: str) -> bool:
    """Delete a make-up class session for a specific student."""
    if not mssv or not uid:
        return False
    events = load_makeup_classes(mssv)
    filtered = [e for e in events if e.uid != uid]
    if len(filtered) != len(events):
        return save_makeup_classes(mssv, filtered)
    return False
