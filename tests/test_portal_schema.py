"""
Unit tests for portal schema validation, schedule parsing durability, and expiry events.
"""

from datetime import datetime, date, time, timedelta
import pytest

from src.portal_schema import (
    validate_semester_payload,
    validate_exam_payload,
    PortalFormatError,
)
from src.schedule_parser import (
    parse_semester_schedule,
    parse_exam_schedule,
    make_expiry_event,
    CalendarEvent,
)
from src.branding import DATA_TTL_DAYS


def test_validate_semester_payload_empty():
    assert validate_semester_payload([]) == []
    assert validate_semester_payload({}) == []
    assert validate_semester_payload(None) == []


def test_validate_semester_payload_invalid_type():
    with pytest.raises(PortalFormatError):
        validate_semester_payload("invalid string payload")


def test_validate_semester_payload_malformed_keys():
    bad_data = [
        {"foo": 1, "bar": 2},
        {"baz": "hello"},
    ]
    with pytest.raises(PortalFormatError):
        validate_semester_payload(bad_data)


def test_validate_semester_payload_valid():
    good_data = [
        {
            "TenHP": "Toán rời rạc",
            "Thu": "Thứ 2",
            "PeriodID": 1,
            "NumberOfPeriods": 3,
            "BeginDate": "2026-09-01",
            "EndDate": "2026-12-15",
            "MaLHP": "MATH101",
            "HoTenGV": "Nguyễn Văn A",
            "Phong": "A1-101",
            "CampusName": "Khu A",
        }
    ]
    items = validate_semester_payload(good_data)
    assert len(items) == 1
    assert items[0]["TenHP"] == "Toán rời rạc"


def test_parse_semester_schedule_clean_format_and_no_guessing():
    data = [
        # Valid item
        {
            "TenHP": "Toán rời rạc",
            "Thu": "Thứ 2",
            "PeriodID": 1,
            "NumberOfPeriods": 3,
            "BeginDate": "2026-09-07",
            "EndDate": "2026-09-14",
            "MaLHP": "MATH101",
            "HoTenGV": "Nguyễn Văn A",
            "Phong": "A1-101",
            "CampusName": "Khu A",
        },
        # Item missing weekday (must NOT guess Monday, must skip)
        {
            "TenHP": "Vật lý đại cương",
            "Thu": None,
            "DayOfWeek": None,
            "PeriodID": 4,
            "NumberOfPeriods": 3,
            "BeginDate": "2026-09-07",
            "EndDate": "2026-09-14",
        },
        # Item missing date (must skip)
        {
            "TenHP": "Hóa học",
            "Thu": "Thứ 3",
            "PeriodID": 1,
            "BeginDate": None,
        },
    ]

    events, skipped = parse_semester_schedule(data)
    assert skipped == 2
    assert len(events) >= 1

    ev = events[0]
    # Clean title: ONLY subject name, no code prefix, no emoji
    assert ev.title == "Toán rời rạc"
    # Clean location: Phòng {room} · {campus}
    assert ev.location == "Phòng A1-101 · Khu A"
    # Clean description: 5 lines, contains UTE-Calendar, no emoji
    assert "Mã lớp: MATH101" in ev.description
    assert "Giảng viên: Nguyễn Văn A" in ev.description
    assert "Tiết 1-3" in ev.description
    assert "Cơ sở: Khu A" in ev.description
    assert "UTE-Calendar" in ev.description


def test_parse_exam_schedule_with_and_without_time():
    exam_data = [
        # Normal exam with time
        {
            "TenHP": "Giải tích 1",
            "MaHP": "CALC1",
            "NgayThi": "15/12/2026",
            "GioThi": "07:30",
            "ThoiLuong": 90,
            "PhongThi": "A2-202",
            "DiaDiem": "Khu A",
            "KyThi": "Cuối kỳ",
            "SBD": "123",
        },
        # Exam missing time -> must be all-day
        {
            "TenHP": "Triết học Mác-Lênin",
            "MaHP": "PHIL1",
            "NgayThi": "20/12/2026",
            "GioThi": None,
            "TimeExam": None,
            "PhongThi": "B1-303",
            "DiaDiem": "Khu B",
            "KyThi": "Cuối kỳ",
        },
        # Invalid exam missing date -> skipped
        {
            "TenHP": "Anh văn 1",
            "MaHP": "ENG1",
            "NgayThi": None,
        },
    ]

    events, skipped = parse_exam_schedule(exam_data)
    assert skipped == 1
    assert len(events) == 2

    # Check normal exam
    ev_normal = [e for e in events if "Giải tích 1" in e.title][0]
    assert ev_normal.title == "Thi: Giải tích 1"
    assert ev_normal.is_all_day is False
    assert ev_normal.location == "Phòng A2-202 · Khu A"
    assert "Giờ thi: 07:30" in ev_normal.description
    assert "Số báo danh: 123" in ev_normal.description
    assert "UTE-Calendar" in ev_normal.description

    # Check exam missing time -> all-day
    ev_all_day = [e for e in events if "Triết học" in e.title][0]
    assert ev_all_day.title == "Thi: Triết học Mác-Lênin"
    assert ev_all_day.is_all_day is True
    assert "Giờ thi: Giờ thi chưa có trên cổng trường" in ev_all_day.description
    assert ev_all_day.location == "Phòng B1-303 · Khu B"
    assert "UTE-Calendar" in ev_all_day.description


def test_make_expiry_event():
    ref_dt = datetime(2026, 9, 1, 10, 0, 0)
    exp_ev = make_expiry_event(ref_dt, "https://ute-calendar.com")

    assert exp_ev.title == "UTE-Calendar: lịch sắp hết hạn"
    assert exp_ev.is_all_day is True
    expected_date = (ref_dt + timedelta(days=DATA_TTL_DAYS) - timedelta(days=3)).date()
    assert exp_ev.start_datetime.date() == expected_date
    assert "https://ute-calendar.com" in exp_ev.description
