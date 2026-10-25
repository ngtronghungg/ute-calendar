from src.branding import APP_NAME
"""
iCalendar (.ics) Exporter
Exports calendar events to standard .ics format for instant import into Google Calendar,
Apple Calendar, Microsoft Outlook, etc.
"""

import os
from datetime import datetime, timezone, timedelta, date
from typing import List, Optional
from icalendar import Calendar, Event as ICalEvent, Alarm, Timezone, TimezoneStandard
from src.schedule_parser import CalendarEvent

# Fixed UTC+7 timezone named Asia/Ho_Chi_Minh without relying on system tzdata
VIETNAM_TZ = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")


def create_ical_calendar(
    events: List[CalendarEvent],
    calendar_name: str = f"{APP_NAME} - Thời khóa biểu & Lịch thi",
    add_reminders: bool = True,
    calendar_color: Optional[str] = None,
    reminder_min: int = 20,
) -> Calendar:
    """Create an icalendar.Calendar object strictly pinned to Asia/Ho_Chi_Minh (UTC+7)."""
    cal = Calendar()
    cal.add("prodid", f"-//{APP_NAME}//VN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", calendar_name)
    cal.add("x-wr-timezone", "Asia/Ho_Chi_Minh")

    if calendar_color:
        cal.add("color", calendar_color)
        cal.add("x-apple-calendar-color", calendar_color)

    # RFC 5545 VTIMEZONE component for Asia/Ho_Chi_Minh
    vtz = Timezone()
    vtz.add("tzid", "Asia/Ho_Chi_Minh")
    vtz_std = TimezoneStandard()
    vtz_std.add("dtstart", datetime(1970, 1, 1, 0, 0, 0))
    vtz_std.add("tzoffsetfrom", timedelta(hours=7))
    vtz_std.add("tzoffsetto", timedelta(hours=7))
    vtz_std.add("tzname", "+07")
    vtz.add_component(vtz_std)
    cal.add_component(vtz)

    import re
    from src.schedule_parser import assign_course_colors, get_course_color
    assign_course_colors(events)

    for ev in events:
        ie = ICalEvent()
        ie.add("summary", ev.title)
        ie.add("uid", f"{ev.uid}@hcmute.edu.vn")
        ie.add("dtstamp", datetime.now(timezone.utc))

        if getattr(ev, "is_all_day", False):
            ie.add("dtstart", ev.start_datetime.date())
            ie.add("dtend", ev.end_datetime.date())
        else:
            # Explicit Vietnam Timezone (UTC+7)
            st_vn = ev.start_datetime.replace(tzinfo=VIETNAM_TZ) if ev.start_datetime.tzinfo is None else ev.start_datetime
            en_vn = ev.end_datetime.replace(tzinfo=VIETNAM_TZ) if ev.end_datetime.tzinfo is None else ev.end_datetime
            ie.add("dtstart", st_vn)
            ie.add("dtend", en_vn)

        if ev.location:
            ie.add("location", ev.location)
        if ev.description:
            ie.add("description", ev.description)

        ev_type = (ev.event_type or "").upper()
        # Set category, priority & distinct color (RFC 7986 / Apple Calendar)
        if ev_type == "EXAM":
            ie.add("color", "#ED1C24")  # Red for exams
            ie.add("x-apple-calendar-color", "#ED1C24")
            ie.add("priority", 1)  # Highest priority
            ie.add("categories", ["LỊCH THI", "EXAM", "HCMUTE"])
        elif ev_type in ("DEADLINE", "REMINDER"):
            color_c = "#D8B26A"
            ie.add("color", color_c)
            ie.add("x-apple-calendar-color", color_c)
            ie.add("priority", 2)
            ie.add("categories", ["NHẮC NHỞ", "DEADLINE", "HCMUTE"])
        else:
            hex_c = getattr(ev, "color_hex", "") or get_course_color(ev.title)[1]
            ie.add("color", hex_c)
            ie.add("x-apple-calendar-color", hex_c)
            ie.add("priority", 5)
            clean_sub = re.sub(r"\[.*?\]|\(.*?\)", "", ev.title).strip()
            ie.add("categories", [clean_sub or "THỜI KHÓA BIỂU", "CLASS", "HCMUTE"])

        # Configure alarms
        if add_reminders and reminder_min > 0:
            if ev.event_type == "CLASS":
                alarm = Alarm()
                alarm.add("action", "DISPLAY")
                alarm.add("description", f"Sắp đến giờ học: {ev.title}")
                alarm.add("trigger", timedelta(minutes=-reminder_min))
                ie.add_component(alarm)
            elif ev.event_type == "EXAM":
                alarm1 = Alarm()
                alarm1.add("action", "DISPLAY")
                alarm1.add("description", f"Lịch thi ngày mai: {ev.title}")
                alarm1.add("trigger", timedelta(days=-1))
                ie.add_component(alarm1)

                alarm2 = Alarm()
                alarm2.add("action", "DISPLAY")
                alarm2.add("description", f"Sắp đến giờ thi: {ev.title}")
                alarm2.add("trigger", timedelta(hours=-2))
                ie.add_component(alarm2)
            elif ev.event_type == "DEADLINE":
                alarm1 = Alarm()
                alarm1.add("action", "DISPLAY")
                alarm1.add("description", f"Hạn chót ngày mai: {ev.title}")
                alarm1.add("trigger", timedelta(days=-1))
                ie.add_component(alarm1)

        cal.add_component(ie)

    return cal


def events_to_ics_bytes(
    events: List[CalendarEvent],
    calendar_name: str = f"{APP_NAME} - Thời khóa biểu & Lịch thi",
    add_reminders: bool = True,
    calendar_color: Optional[str] = None,
    reminder_min: int = 20,
) -> bytes:
    """Generate iCalendar bytes directly in memory."""
    cal = create_ical_calendar(
        events,
        calendar_name=calendar_name,
        add_reminders=add_reminders,
        calendar_color=calendar_color,
        reminder_min=reminder_min,
    )
    return cal.to_ical()


def export_events_to_ics(
    events: List[CalendarEvent],
    output_path: str = "data/hcmute_schedule.ics",
    calendar_name: str = f"{APP_NAME} - Thời khóa biểu & Lịch thi",
    add_reminders: bool = True,
    calendar_color: Optional[str] = None,
    reminder_min: int = 20,
) -> str:
    """
    Export a list of CalendarEvent objects to an iCalendar (.ics) file.
    """
    cal = create_ical_calendar(
        events,
        calendar_name=calendar_name,
        add_reminders=add_reminders,
        calendar_color=calendar_color,
        reminder_min=reminder_min,
    )
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(cal.to_ical())

    return os.path.abspath(output_path)
