"""
Unit tests for Calendar Options, Feed Variants, and Durability.
"""

import json
from datetime import datetime, timedelta
import pytest
from src.web_server import app, storage, DATA_TTL_SECONDS
from src.schedule_parser import CalendarEvent


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def auth_student():
    mssv = "21110123"
    token = "test_sess_token_options"
    storage.set_json(
        f"session:{token}",
        {
            "mssv": mssv,
            "name": "Nguyễn Văn Test",
            "created_at": datetime.now().isoformat(),
        },
        ttl=3600,
    )
    # Seed mock classes and exams in cache
    cls_event = CalendarEvent(
        uid="hcmute-class-MATH101-20260907-p1",
        title="Toán rời rạc",
        start_datetime=datetime.now() + timedelta(days=1),
        end_datetime=datetime.now() + timedelta(days=1, hours=2),
        location="Phòng A1-101 · Khu A",
        description="Mã lớp: MATH101\nTiết 1-3 (07:30 - 09:45)\nCơ sở: Khu A\nUTE-Calendar",
        event_type="CLASS",
    )
    exam_event = CalendarEvent(
        uid="hcmute-exam-MATH101-20261215-0730",
        title="Thi: Toán rời rạc",
        start_datetime=datetime.now() + timedelta(days=30),
        end_datetime=datetime.now() + timedelta(days=30, hours=2),
        location="Phòng A1-202 · Khu A",
        description="Kỳ thi: Cuối kỳ\nMã học phần: MATH101\nGiờ thi: 07:30 (90 phút)\nUTE-Calendar",
        event_type="EXAM",
    )
    from src.schedule_cache import save_feed_cache, save_cached_exams
    save_feed_cache([cls_event], mssv=mssv)
    save_cached_exams([exam_event], mssv=mssv)

    yield mssv, token

    # Cleanup
    storage.delete(f"session:{token}")
    storage.delete(f"feed_cache:{mssv}")
    storage.delete(f"exam_cache:{mssv}")
    storage.delete(f"feedopt:{mssv}")


def test_options_requires_auth(client):
    res = client.post("/api/calendar/options", json={"reminder_min": 20})
    assert res.status_code == 401


def test_options_validation_invalid_reminder(client, auth_student):
    mssv, token = auth_student
    res = client.post(
        "/api/calendar/options",
        headers={"Authorization": f"Bearer {token}"},
        json={"reminder_min": 999},  # Invalid
    )
    assert res.status_code == 400
    data = res.get_json()
    assert "Số phút nhắc nhở không hợp lệ" in data["message"]


def test_options_validation_invalid_title_style(client, auth_student):
    mssv, token = auth_student
    res = client.post(
        "/api/calendar/options",
        headers={"Authorization": f"Bearer {token}"},
        json={"title_style": "invalid_style"},
    )
    assert res.status_code == 400
    data = res.get_json()
    assert "Kiểu hiển thị tiêu đề không hợp lệ" in data["message"]


def test_options_save_and_split(client, auth_student):
    mssv, token = auth_student

    # 1. Update options to split = True
    res = client.post(
        "/api/calendar/options",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "reminder_min": 15,
            "title_style": "name",
            "split": True,
            "deadlines": False,
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["options"]["reminder_min"] == 15
    assert data["options"]["split"] is True

    # Calendars must have tkb and thi
    cal_ids = [c["id"] for c in data["calendars"]]
    assert "tkb" in cal_ids
    assert "thi" in cal_ids

    # 2. GET /api/calendar/feed-token returns current options and calendars
    get_res = client.get(
        "/api/calendar/feed-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 200
    get_data = get_res.get_json()
    assert get_data["options"]["reminder_min"] == 15
    assert len(get_data["calendars"]) == 2

    # 3. Test downloading variant tkb with download=1
    feed_tok = get_data["feed_token"]
    feed_res = client.get(f"/calendar/{feed_tok}/tkb.ics?download=1")
    assert feed_res.status_code == 200
    assert "text/calendar" in feed_res.content_type
    assert 'attachment; filename="ute-calendar-tkb.ics"' in feed_res.headers.get("Content-Disposition", "")
    ics_text = feed_res.data.decode("utf-8")
    assert "Toán rời rạc" in ics_text
    # Must have expiry event in tkb
    assert "UTE-Calendar: lịch sắp hết hạn" in ics_text

    # 4. Test thi.ics (must NOT have expiry event)
    thi_res = client.get(f"/calendar/{feed_tok}/thi.ics")
    assert thi_res.status_code == 200
    thi_text = thi_res.data.decode("utf-8")
    assert "Thi: Toán rời rạc" in thi_text
    assert "UTE-Calendar: lịch sắp hết hạn" not in thi_text
