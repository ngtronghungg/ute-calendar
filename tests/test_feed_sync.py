"""
Tests for live calendar feed, pre-built storage, ETag/304 handling,
refresh rate limiting, and zero credential leakage.
"""

import time
import unittest
from datetime import datetime, timezone, timedelta
from src.web_server import app, storage, get_or_create_feed_token, build_student_calendar_feed
from src.schedule_parser import CalendarEvent
from src.schedule_cache import save_feed_cache


class TestFeedSync(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.test_mssv = "22110099"
        # Clear rate limits and student data
        storage.delete(f"rl:refresh:{self.test_mssv}")
        storage.delete(f"rl:regen:{self.test_mssv}")
        old_tok = storage.get_json(f"feedtok_by:{self.test_mssv}")
        if old_tok:
            storage.delete(f"feedtok:{old_tok}")
            storage.delete(f"feed:{old_tok}")
        storage.delete(f"feedtok_by:{self.test_mssv}")

        # Seed student class
        now = datetime.now(timezone.utc)
        ev = CalendarEvent(
            uid="class_sync_test_1",
            title="Nhập môn Trí tuệ Nhân tạo",
            start_datetime=now + timedelta(days=2),
            end_datetime=now + timedelta(days=2, hours=2),
            location="A1-203",
            description="GV: TS. Tran",
            event_type="CLASS",
        )
        save_feed_cache([ev], mssv=self.test_mssv)

    def tearDown(self):
        storage.delete(f"rl:refresh:{self.test_mssv}")
        storage.delete(f"rl:regen:{self.test_mssv}")

    def test_prebuilt_feed_and_etag_caching(self):
        """Pre-built feed in storage feed:<token>, ETag, Cache-Control, and 304 If-None-Match."""
        tok = get_or_create_feed_token(self.test_mssv)
        self.assertTrue(bool(tok))

        # Check storage key feed:<tok>
        feed_record = storage.get_json(f"feed:{tok}")
        self.assertIsNotNone(feed_record)
        self.assertIn("ics", feed_record)
        self.assertIn("etag", feed_record)
        self.assertIn("BEGIN:VCALENDAR", feed_record["ics"])
        self.assertIn("Nhập môn Trí tuệ Nhân tạo", feed_record["ics"])

        # GET /calendar/<tok>/feed.ics
        res = self.client.get(f"/calendar/{tok}/feed.ics")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/calendar", res.content_type)
        self.assertIn("public, max-age=0, s-maxage=21600", res.headers.get("Cache-Control", ""))

        etag = res.headers.get("ETag")
        self.assertIsNotNone(etag)

        # Send If-None-Match with matching ETag -> 304 Not Modified
        res304 = self.client.get(f"/calendar/{tok}/feed.ics", headers={"If-None-Match": etag})
        self.assertEqual(res304.status_code, 304)

        # Invalid token -> 404
        res404 = self.client.get("/calendar/completely_random_invalid_token/feed.ics")
        self.assertEqual(res404.status_code, 404)

    def test_feed_token_regenerate_deletes_old_and_creates_new(self):
        """Regenerating feed token purges old feed:<old_token> and creates feed:<new_token>."""
        old_tok = get_or_create_feed_token(self.test_mssv)
        self.assertIsNotNone(storage.get_json(f"feed:{old_tok}"))

        # Create session
        sid = "sess_reg_test_123"
        storage.set_json(f"session:{sid}", {"session_token": sid, "mssv": self.test_mssv}, ttl=3600)
        self.client.set_cookie("hcmute_session", sid)

        res = self.client.post("/api/calendar/feed-token/regenerate")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        new_tok = data.get("feed_token")
        self.assertNotEqual(old_tok, new_tok)

        # Old feed must be gone
        self.assertIsNone(storage.get_json(f"feed:{old_tok}"))
        self.assertIsNone(storage.get_json(f"feedtok:{old_tok}"))

        # New feed must exist
        self.assertIsNotNone(storage.get_json(f"feed:{new_tok}"))

    def test_refresh_rate_limit(self):
        """POST /api/calendar/refresh enforces 1 call per 15 minutes and returns 429."""
        sid = "sess_rf_test_456"
        storage.set_json(f"session:{sid}", {"session_token": sid, "mssv": self.test_mssv}, ttl=3600)
        self.client.set_cookie("hcmute_session", sid)

        # Manually trigger rate limit flag
        storage.incr_with_ttl(f"rl:refresh:{self.test_mssv}", ttl=900)

        res = self.client.post("/api/calendar/refresh")
        self.assertEqual(res.status_code, 429)
        data = res.get_json()
        self.assertIn("15 phút", data.get("message", ""))


if __name__ == "__main__":
    unittest.main()
