"""
HCMUTE Schedule Parser
Parses raw JSON from HCMUTE schedule endpoints into clean, standardized class session events.
"""

from datetime import datetime, date, time, timedelta
from typing import List, Dict, Any, Optional, Tuple
import re

from src.portal_schema import (
    validate_semester_payload,
    validate_exam_payload,
    PortalFormatError,
)
from src.branding import DATA_TTL_DAYS


# Official HCMUTE Period Time Table (Khung giờ giảng dạy và học tập trực tiếp trên lớp HCMUTE)
PERIOD_TABLE: Dict[int, Dict[str, time]] = {
    1: {"start": time(7, 30), "end": time(8, 15)},
    2: {"start": time(8, 15), "end": time(9, 0)},
    3: {"start": time(9, 0), "end": time(9, 45)},
    4: {"start": time(10, 0), "end": time(10, 45)},
    5: {"start": time(10, 45), "end": time(11, 30)},
    6: {"start": time(11, 30), "end": time(12, 15)},
    7: {"start": time(12, 45), "end": time(13, 30)},
    8: {"start": time(13, 30), "end": time(14, 15)},
    9: {"start": time(14, 15), "end": time(15, 0)},
    10: {"start": time(15, 15), "end": time(16, 0)},
    11: {"start": time(16, 0), "end": time(16, 45)},
    12: {"start": time(16, 45), "end": time(17, 30)},
    13: {"start": time(18, 0), "end": time(18, 45)},
    14: {"start": time(18, 45), "end": time(19, 30)},
    15: {"start": time(19, 30), "end": time(20, 15)},
    16: {"start": time(20, 15), "end": time(21, 0)},
}

# Day of week mapping: HCMUTE uses DayOfWeek: 1=Mon .. 7=Sun, or Vietnamese text
DAY_MAP: Dict[Any, int] = {
    "thứ hai": 0, "thứ 2": 0, "monday": 0, "mon": 0, 2: 0, "2": 0,
    "thứ ba": 1, "thứ 3": 1, "tuesday": 1, "tue": 1, 3: 1, "3": 1,
    "thứ tư": 2, "thứ 4": 2, "wednesday": 2, "wed": 2, 4: 2, "4": 2,
    "thứ năm": 3, "thứ 5": 3, "thursday": 3, "thu": 3, 5: 3, "5": 3,
    "thứ sáu": 4, "thứ 6": 4, "friday": 4, "fri": 4, 6: 4, "6": 4,
    "thứ bảy": 5, "thứ 7": 5, "saturday": 5, "sat": 5, 7: 5, "7": 5,
    "chủ nhật": 6, "cn": 6, "sunday": 6, "sun": 6, 8: 6, "8": 6, 1: 0, "1": 0,
}


# 9 Distinct, vibrant Google Calendar & iCal colors for Courses
# Excludes Color 11 (Tomato) and Color 4 (Flamingo) which are reserved for Exams & Deadlines
COURSE_COLOR_PALETTE = [
    ("7", "#6DB3E8"),  # Xanh sáng
    ("5", "#D8B26A"),  # Vàng đất
    ("2", "#8FB996"),  # Xanh xô thơm
    ("3", "#B9A0D6"),  # Tím lavender
    ("6", "#E0927F"),  # Cam đất
    ("9", "#7FC4C0"),  # Xanh mòng két
    ("10", "#C9B38B"), # Cát vàng
    ("8", "#9AA3B5"),  # Xám xanh
]


def get_course_color(course_name: str) -> tuple[str, str]:
    """
    Deterministically map a course name to a Google Calendar colorId and hex color.
    Guarantees every session of the same course gets the identical color,
    while different courses get different colors.
    """
    if not course_name:
        return COURSE_COLOR_PALETTE[0]

    clean_name = re.sub(r"\[.*?\]|\(.*?\)", "", course_name).strip().lower()
    if not clean_name:
        clean_name = course_name.lower().strip()

    h = 0
    for i, char in enumerate(clean_name):
        h = (h * 37 + ord(char) * (i + 7)) & 0xFFFFFFFF
    idx = h % len(COURSE_COLOR_PALETTE)
    return COURSE_COLOR_PALETTE[idx]


def assign_course_colors(events: List["CalendarEvent"]) -> None:
    """
    Ensure each distinct course in the event list receives a unique, collision-free color from the palette,
    while exam events are guaranteed to receive Tomato Red (Color 11, #d50000).
    """
    course_titles = []
    for ev in events:
        if (ev.event_type or "").upper() in ("CLASS", "TKB"):
            clean_title = re.sub(r"\[.*?\]|\(.*?\)", "", ev.title)
            clean_title = re.sub(r"^[🌀-🧿☀-➿\s]+", "", clean_title).strip()
            if clean_title and clean_title not in course_titles:
                course_titles.append(clean_title)

    color_map = {}
    for idx, ct in enumerate(course_titles):
        color_map[ct] = COURSE_COLOR_PALETTE[idx % len(COURSE_COLOR_PALETTE)]

    for ev in events:
        ev_type = (ev.event_type or "").upper()
        if ev_type == "EXAM":
            ev.color_id = "11"  # Tomato
            ev.color_hex = "#d50000"
            clean_exam = re.sub(r"^(\[LỊCH THI\]|[🌀-🧿☀-➿]|\s)+", "", ev.title).strip()
            if not clean_exam.startswith("Thi:"):
                ev.title = f"Thi: {clean_exam}"
            else:
                ev.title = clean_exam
        elif ev_type == "DEADLINE":
            ev.color_id = "4"   # Flamingo
            ev.color_hex = "#e67c73"
            clean_d = re.sub(r"^(\[NHẮC NHỞ\]|[🌀-🧿☀-➿]|\s)+", "", ev.title).strip()
            ev.title = clean_d
        else:
            clean_title = re.sub(r"\[.*?\]|\(.*?\)", "", ev.title)
            clean_title = re.sub(r"^[🌀-🧿☀-➿\s]+", "", clean_title).strip()
            if clean_title in color_map:
                ev.color_id, ev.color_hex = color_map[clean_title]
            else:
                ev.color_id, ev.color_hex = get_course_color(ev.title)

            raw_title = re.sub(r"^[🌀-🧿☀-➿\s]+", "", ev.title).strip()
            ev.title = raw_title


class CalendarEvent:
    """Standardized Calendar Event Model."""

    def __init__(
        self,
        uid: str,
        title: str,
        start_datetime: datetime,
        end_datetime: datetime,
        location: str = "",
        description: str = "",
        event_type: str = "CLASS",  # CLASS, EXAM, DEADLINE, REMINDER
        category: str = "ACADEMIC",
        is_all_day: bool = False,
        color_id: str = "",
        color_hex: str = "",
    ):
        self.uid = uid
        self.title = title
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime
        self.location = location
        self.description = description
        self.event_type = event_type
        self.category = category
        self.is_all_day = is_all_day

        if color_id and color_hex:
            self.color_id = color_id
            self.color_hex = color_hex
        elif (event_type or "").upper() == "EXAM":
            self.color_id = "11"  # Tomato
            self.color_hex = "#d50000"
        elif (event_type or "").upper() == "DEADLINE":
            self.color_id = "4"   # Flamingo
            self.color_hex = "#e67c73"
        elif (event_type or "").upper() == "REMINDER":
            self.color_id = "5"
            self.color_hex = "#D8B26A"
        else:
            cid, hex_c = get_course_color(self.title)
            self.color_id = cid
            self.color_hex = hex_c

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "title": self.title,
            "start": self.start_datetime.isoformat(),
            "end": self.end_datetime.isoformat(),
            "location": self.location,
            "description": self.description,
            "event_type": self.event_type,
            "category": self.category,
            "is_all_day": self.is_all_day,
            "color_id": self.color_id,
            "color_hex": self.color_hex,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CalendarEvent":
        return cls(
            uid=d["uid"],
            title=d["title"],
            start_datetime=datetime.fromisoformat(d["start"]),
            end_datetime=datetime.fromisoformat(d["end"]),
            location=d.get("location", ""),
            description=d.get("description", ""),
            event_type=d.get("event_type", "CLASS"),
            category=d.get("category", "ACADEMIC"),
            is_all_day=d.get("is_all_day", False),
            color_id=d.get("color_id", ""),
            color_hex=d.get("color_hex", ""),
        )

    def __repr__(self) -> str:
        return f"<Event {self.title} at {self.start_datetime.strftime('%Y-%m-%d %H:%M')}>"


def parse_period_range(period_str: Any) -> tuple[Optional[int], Optional[int]]:
    """
    Extract start and end periods from strings like:
    '1-3', '1 -> 3', '1,2,3', 'Tiết 7-9', '10', 1
    Returns (None, None) if no digits found (no guessing).
    """
    if period_str is None:
        return None, None
    s = str(period_str).strip()
    digits = [int(m) for m in re.findall(r"\d+", s)]
    if not digits:
        return None, None
    if len(digits) == 1:
        return digits[0], digits[0]
    return min(digits), max(digits)


def parse_date_safely(date_val: Any) -> Optional[date]:
    """Parse string or datetime to date object."""
    if not date_val:
        return None
    if isinstance(date_val, datetime):
        return date_val.date()
    if isinstance(date_val, date):
        return date_val

    s = str(date_val).strip()
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        m_iso = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
        if m_iso:
            return date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
        m_dmy = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s)
        if m_dmy:
            return date(int(m_dmy.group(3)), int(m_dmy.group(2)), int(m_dmy.group(1)))
        return datetime.fromisoformat(s).date()
    except Exception:
        return None


def get_period_time(start_p: int, end_p: int) -> tuple[time, time]:
    """Get start and end time objects for period range."""
    start_p = max(1, min(start_p, 16))
    end_p = max(start_p, min(end_p, 16))

    start_t = PERIOD_TABLE.get(start_p, {}).get("start", time(7, 30))
    end_t = PERIOD_TABLE.get(end_p, {}).get("end", time(11, 30))
    return start_t, end_t


def parse_semester_schedule(data: Any) -> Tuple[List[CalendarEvent], int]:
    """
    Parse result of DrawingStudentSchedule_Perior into individual class events.
    Returns (events, skipped_count).
    Rule: Strict validation, no guessing.
    """
    items = validate_semester_payload(data)
    events: List[CalendarEvent] = []
    skipped_count = 0

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue

        # Skip unassigned classes (Chưa Xếp TKB)
        xep_tkb = str(item.get("XepTKB") or "").strip().lower()
        if "chưa xếp" in xep_tkb or "không xếp" in xep_tkb:
            continue

        subject_name = (
            item.get("TenHP")
            or item.get("ClassCourseName")
            or item.get("CurriculumName")
            or item.get("TenMonHoc")
            or "Môn học"
        ).strip()

        subject_code = (
            item.get("MaLHP")
            or item.get("ClassCourseID")
            or item.get("CurriculumID")
            or item.get("MaHP")
            or ""
        ).strip()

        lecturer = (
            item.get("HoTenGV")
            or item.get("ProfessorName")
            or item.get("GiangVien")
            or ""
        ).strip()

        room = (
            item.get("Phong")
            or item.get("Classroom")
            or item.get("RoomID")
            or "Chưa xếp phòng"
        ).strip()

        campus = (item.get("CampusName") or "HCMUTE").strip()

        # Day of week
        raw_thu = str(item.get("Thu") or "").strip().lower()
        target_weekday = DAY_MAP.get(raw_thu)
        if target_weekday is None:
            day_of_week_num = item.get("DayOfWeek")
            if day_of_week_num is not None:
                try:
                    # In HCMUTE, DayOfWeek 1=Monday (0), 2=Tuesday (1), ..., 7=Sunday (6)
                    target_weekday = int(day_of_week_num) - 1
                except (ValueError, TypeError):
                    pass

        if target_weekday is None:
            for k, v in DAY_MAP.items():
                if str(k).lower() in raw_thu:
                    target_weekday = v
                    break

        # Rule of no guessing: if weekday is not resolved, skip session!
        if target_weekday is None or target_weekday < 0 or target_weekday > 6:
            skipped_count += 1
            continue

        # Periods: check PeriodID & NumberOfPeriods
        start_p = None
        end_p = None
        if item.get("PeriodID"):
            try:
                start_p = int(item.get("PeriodID"))
                num_p = int(item.get("NumberOfPeriods") or 3)
                end_p = start_p + num_p - 1
            except (ValueError, TypeError):
                raw_period = item.get("PeriodID") or item.get("CaHoc") or item.get("Tiet") or item.get("TietHoc")
                start_p, end_p = parse_period_range(raw_period)
        else:
            raw_period = item.get("CaHoc") or item.get("Tiet") or item.get("TietHoc")
            start_p, end_p = parse_period_range(raw_period)

        if start_p is None or end_p is None or start_p < 1 or end_p < start_p:
            skipped_count += 1
            continue

        start_t, end_t = get_period_time(start_p, end_p)

        # Start & End dates
        tuan_raw = str(item.get("TuanHoc") or item.get("WeekSchedule") or "")
        m_range = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s*->\s*(\d{1,2}/\d{1,2}/\d{4})", tuan_raw)

        begin_d = None
        end_d = None
        if m_range:
            begin_d = parse_date_safely(m_range.group(1))
            end_d = parse_date_safely(m_range.group(2))

        if not begin_d:
            raw_begin = item.get("BeginDate") or item.get("TuNgay") or item.get("TimeBeginDate")
            begin_d = parse_date_safely(raw_begin)

        if not end_d:
            raw_end = item.get("EndDate") or item.get("DenNgay")
            end_d = parse_date_safely(raw_end)

        # Rule of no guessing: if begin_d is missing, skip session
        if not begin_d:
            skipped_count += 1
            continue
        if not end_d:
            end_d = begin_d + timedelta(weeks=15)

        # Generate each session occurrence
        curr_d = begin_d
        days_ahead = (target_weekday - curr_d.weekday()) % 7
        curr_d += timedelta(days=days_ahead)

        # Event content formatting
        # Title: only subject name, clean, no code prefix, no emoji
        title = subject_name

        # Location: Phòng {room} · {campus} or Chưa xếp phòng · {campus}
        if room and "chưa xếp" not in room.lower() and room.lower() != "null":
            location_str = f"Phòng {room} · {campus}"
        else:
            location_str = f"Chưa xếp phòng · {campus}"

        # Description: clean 5-line format with UTE-Calendar
        desc_lines = [f"Mã lớp: {subject_code}"]
        if lecturer and lecturer.lower() != "chưa cập nhật":
            desc_lines.append(f"Giảng viên: {lecturer}")
        desc_lines.append(f"Tiết {start_p}-{end_p} ({start_t.strftime('%H:%M')} - {end_t.strftime('%H:%M')})")
        desc_lines.append(f"Cơ sở: {campus}")
        desc_lines.append("UTE-Calendar")
        desc = "\n".join(desc_lines)

        while curr_d <= end_d:
            start_dt = datetime.combine(curr_d, start_t)
            end_dt = datetime.combine(curr_d, end_t)

            uid = f"hcmute-class-{subject_code or idx}-{curr_d.strftime('%Y%m%d')}-p{start_p}"

            events.append(
                CalendarEvent(
                    uid=uid,
                    title=title,
                    start_datetime=start_dt,
                    end_datetime=end_dt,
                    location=location_str,
                    description=desc,
                    event_type="CLASS",
                    category="ACADEMIC",
                )
            )

            curr_d += timedelta(days=7)

    assign_course_colors(events)
    return events, skipped_count


def parse_exam_schedule(exam_data: Any) -> Tuple[List[CalendarEvent], int]:
    """
    Parse exam schedule into calendar events.
    Returns (events, skipped_count).
    Supports both student/exam and student/showexambytime formats.
    """
    items = validate_exam_payload(exam_data)
    events: List[CalendarEvent] = []
    seen_exams = set()
    skipped_count = 0

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue

        subject = (
            item.get("CurriculumName")
            or item.get("TenHP")
            or item.get("TenMonHoc")
            or item.get("ClassCourseName")
            or "Thi môn học"
        ).strip()

        code = (item.get("CurriculumID") or item.get("MaHP") or item.get("MaLHP") or "").strip()
        room = (item.get("PhongThi") or item.get("Phong") or "Xem thông báo").strip()
        location = (item.get("DiaDiem") or "HCMUTE").strip()
        exam_type = (item.get("KyThi") or "Thi kết thúc học phần").strip()

        exam_date_raw = str(item.get("NgayThi") or item.get("DateExam") or "").strip()
        exam_time_raw = str(item.get("GioThi") or item.get("TimeExam") or "").strip()
        duration = item.get("ThoiLuong") or item.get("ThoiGianLamBai") or 90

        if not exam_date_raw or exam_date_raw.lower() in ("null", "none"):
            skipped_count += 1
            continue

        # Parse date DD/MM/YYYY
        m_date = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", exam_date_raw)
        if not m_date:
            exam_d = parse_date_safely(exam_date_raw)
        else:
            d, m, y = map(int, m_date.groups())
            try:
                exam_d = date(y, m, d)
            except ValueError:
                exam_d = None

        if not exam_d:
            skipped_count += 1
            continue

        # Parse time: e.g. 13g00, 09g45, 13:00, 7h30
        m_time = re.search(r"(\d{1,2})(?:g|h|:)(\d{2})", exam_time_raw, re.IGNORECASE) if exam_time_raw else None

        try:
            dur_mins = int(duration)
        except (ValueError, TypeError):
            dur_mins = 90

        if m_time:
            hh, mm = int(m_time.group(1)), int(m_time.group(2))
            exam_t = time(hh, mm)
            start_dt = datetime.combine(exam_d, exam_t)
            end_dt = start_dt + timedelta(minutes=dur_mins)
            is_all_day = False
            time_line = f"Giờ thi: {start_dt.strftime('%H:%M')} ({dur_mins} phút)"
        else:
            # Rule of no guessing: Missing exam time -> All-day event!
            hh, mm = 0, 0
            is_all_day = True
            start_dt = datetime.combine(exam_d, time(0, 0))
            end_dt = datetime.combine(exam_d + timedelta(days=1), time(0, 0))
            time_line = "Giờ thi: Giờ thi chưa có trên cổng trường"

        # Deduplication
        dedup_key = f"{code}_{exam_d}_{hh}_{mm}"
        if dedup_key in seen_exams:
            continue
        seen_exams.add(dedup_key)

        title = f"Thi: {subject}"
        loc_str = f"Phòng {room} · {location}"

        desc_lines = [
            f"Kỳ thi: {exam_type}",
            f"Mã học phần: {code}",
            time_line,
        ]
        sbd = item.get("SBD") or item.get("SoBaoDanh")
        if sbd and str(sbd).strip().lower() not in ("null", "none", ""):
            desc_lines.append(f"Số báo danh: {str(sbd).strip()}")
        note = item.get("Note") or item.get("GhiChu")
        if note and str(note).strip().lower() not in ("null", "none", ""):
            desc_lines.append(f"Ghi chú: {str(note).strip()}")
        desc_lines.append("UTE-Calendar")
        desc = "\n".join(desc_lines)

        uid = f"hcmute-exam-{code or idx}-{exam_d.strftime('%Y%m%d')}-{hh:02d}{mm:02d}"

        events.append(
            CalendarEvent(
                uid=uid,
                title=title,
                start_datetime=start_dt,
                end_datetime=end_dt,
                location=loc_str,
                description=desc,
                event_type="EXAM",
                category="EXAM",
                is_all_day=is_all_day,
                color_id="11",
                color_hex="#d50000",
            )
        )

    assign_course_colors(events)
    return events, skipped_count


def make_expiry_event(last_refresh_dt: datetime, host_url: str) -> CalendarEvent:
    """
    Creates an all-day expiry notification event occurring 3 days prior to cache TTL.
    Added ONLY to 'all' and 'tkb' feeds; never in 'thi' or 'han-chot'.
    """
    expiry_date = (last_refresh_dt + timedelta(days=DATA_TTL_DAYS) - timedelta(days=3)).date()
    clean_host = host_url.rstrip("/")
    return CalendarEvent(
        uid=f"ute-calendar-expiry-{expiry_date.strftime('%Y%m%d')}",
        title="UTE-Calendar: lịch sắp hết hạn",
        start_datetime=datetime.combine(expiry_date, time(0, 0)),
        end_datetime=datetime.combine(expiry_date + timedelta(days=1), time(0, 0)),
        location="",
        description=f"Mở UTE-Calendar để lấy lịch học kỳ mới: {clean_host}",
        event_type="REMINDER",
        category="REMINDER",
        is_all_day=True,
    )


def guess_current_term(now: Optional[datetime] = None) -> tuple[str, str]:
    """
    Guess academic year and semester from current date:
    - Months 8–12: HK01 of (Y)-(Y+1)
    - Months 1–5:  HK02 of (Y-1)-(Y)
    - Months 6–7:  HK03 of (Y-1)-(Y)
    Returns: (year_str, term_str), e.g. ("2026-2027", "HK01")
    """
    if now is None:
        now = datetime.now()
    y = now.year
    m = now.month
    if m >= 8:
        return f"{y}-{y+1}", "HK01"
    elif m <= 5:
        return f"{y-1}-{y}", "HK02"
    else:
        return f"{y-1}-{y}", "HK03"


def get_available_years(now: Optional[datetime] = None, count: int = 4) -> List[str]:
    """Generate list of academic years ending at current year."""
    if now is None:
        now = datetime.now()
    curr_y, _ = guess_current_term(now)
    base_start = int(curr_y.split("-")[0])
    return [f"{y}-{y+1}" for y in range(base_start - count + 1, base_start + 1)][::-1]
