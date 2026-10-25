"""
TTL and Privacy Verification Tests (Phase 2)
Verifies:
1. 150-day (semester + exam season) TTL applied to all persistent student cache keys.
2. Complete absence of raw student MSSV from the generated calendar feed.
3. GET /api/public-config exposes strictly only the 3 allowed non-sensitive fields.
"""

import unittest
import time
import os
import sys
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.branding import DATA_TTL_DAYS, DATA_TTL_SECONDS
from src import storage
from src.schedule_parser import CalendarEvent
from src.schedule_cache import save_feed_cache, save_cached_exams
from src.schedule_state import save_makeup_classes, add_cancellation
from src.web_server import (
    app,
    get_or_create_feed_token,
    build_student_calendar_feed,
    touch_student_data_ttl,
)


class TestTTLAndPrivacy(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.mock_mssv = "23119988"
        self.expected_ttl = DATA_TTL_SECONDS  # 150 * 86400 = 12,960,000s
        self.margin = 300  # 5 minutes tolerance
        self._cleanup(self.mock_mssv)

    def tearDown(self):
        self._cleanup(self.mock_mssv)
        self._cleanup("24115544")

    def _cleanup(self, mssv):
        storage.delete(f"feed_cache:{mssv}")
        storage.delete(f"exam_cache:{mssv}")
        storage.delete(f"makeup:{mssv}")
        storage.delete(f"cancelled:{mssv}")
        feed_tok = storage.get_json(f"feedtok_by:{mssv}")
        if feed_tok:
            storage.delete(f"feedtok:{feed_tok}")
            storage.delete(f"feed:{feed_tok}")
        storage.delete(f"feedtok_by:{mssv}")

    def test_all_student_keys_have_150_days_ttl(self):
        """Phase 2.1: All student persistent keys must have exp ≈ now + 150 days (± 5 min)."""
        now = time.time()
        ev = CalendarEvent(
            uid="class-ktlt-session1",
            title="Kỹ thuật lập trình",
            start_datetime=datetime.now() + timedelta(days=1),
            end_datetime=datetime.now() + timedelta(days=1, hours=3),
            location="A1-101",
            description="Buổi học thử nghiệm",
            event_type="CLASS",
            category="TKB",
        )

        # 1. feed_cache:<mssv>
        save_feed_cache([ev], mssv=self.mock_mssv)
        entry_feed = storage._read_local_entry(f"feed_cache:{self.mock_mssv}")
        self.assertIsNotNone(entry_feed)
        self.assertIsNotNone(entry_feed.get("exp"))
        self.assertAlmostEqual(entry_feed["exp"], now + self.expected_ttl, delta=self.margin)

        # 2. exam_cache:<mssv>
        exam_ev = CalendarEvent(
            uid="exam-ktlt-session1",
            title="Thi Kỹ thuật lập trình",
            start_datetime=datetime.now() + timedelta(days=10),
            end_datetime=datetime.now() + timedelta(days=10, hours=2),
            location="A2-202",
            description="Lịch thi",
            event_type="EXAM",
            category="THI",
        )
        save_cached_exams([exam_ev], mssv=self.mock_mssv)
        entry_exam = storage._read_local_entry(f"exam_cache:{self.mock_mssv}")
        self.assertIsNotNone(entry_exam)
        self.assertIsNotNone(entry_exam.get("exp"))
        self.assertAlmostEqual(entry_exam["exp"], now + self.expected_ttl, delta=self.margin)

        # 3. makeup:<mssv>
        save_makeup_classes(self.mock_mssv, [ev])
        entry_makeup = storage._read_local_entry(f"makeup:{self.mock_mssv}")
        self.assertIsNotNone(entry_makeup)
        self.assertIsNotNone(entry_makeup.get("exp"))
        self.assertAlmostEqual(entry_makeup["exp"], now + self.expected_ttl, delta=self.margin)

        # 4. cancelled:<mssv>
        add_cancellation(self.mock_mssv, "class-cancelled-uid-123")
        entry_cancelled = storage._read_local_entry(f"cancelled:{self.mock_mssv}")
        self.assertIsNotNone(entry_cancelled)
        self.assertIsNotNone(entry_cancelled.get("exp"))
        self.assertAlmostEqual(entry_cancelled["exp"], now + self.expected_ttl, delta=self.margin)

        # 5. feedtok_by:<mssv> and feedtok:<token>
        token = get_or_create_feed_token(self.mock_mssv)
        self.assertTrue(token)
        entry_tokby = storage._read_local_entry(f"feedtok_by:{self.mock_mssv}")
        self.assertIsNotNone(entry_tokby)
        self.assertIsNotNone(entry_tokby.get("exp"))
        self.assertAlmostEqual(entry_tokby["exp"], now + self.expected_ttl, delta=self.margin)

        entry_tok = storage._read_local_entry(f"feedtok:{token}")
        self.assertIsNotNone(entry_tok)
        self.assertIsNotNone(entry_tok.get("exp"))
        self.assertAlmostEqual(entry_tok["exp"], now + self.expected_ttl, delta=self.margin)

        # 6. feed:<token>
        feed_rec = build_student_calendar_feed(self.mock_mssv, token)
        self.assertIsNotNone(feed_rec)
        entry_feed_data = storage._read_local_entry(f"feed:{token}")
        self.assertIsNotNone(entry_feed_data)
        self.assertIsNotNone(entry_feed_data.get("exp"))
        self.assertAlmostEqual(entry_feed_data["exp"], now + self.expected_ttl, delta=self.margin)

        # 7. Test touch_student_data_ttl refreshes all keys
        touch_student_data_ttl(self.mock_mssv)
        refreshed_feed = storage._read_local_entry(f"feed_cache:{self.mock_mssv}")
        self.assertAlmostEqual(refreshed_feed["exp"], time.time() + self.expected_ttl, delta=self.margin)

    def test_calendar_feed_does_not_contain_mssv(self):
        """Phase 2.5: The generated calendar feed must NOT contain student MSSV anywhere."""
        clean_mssv = "24115544"
        self._cleanup(clean_mssv)
        try:
            ev = CalendarEvent(
                uid="class-math101-session1",
                title="Toán cao cấp",
                start_datetime=datetime.now() + timedelta(days=2),
                end_datetime=datetime.now() + timedelta(days=2, hours=3),
                location="A1-301",
                description="Lớp học chính thức",
                event_type="CLASS",
                category="TKB",
            )
            save_feed_cache([ev], mssv=clean_mssv)
            tok = get_or_create_feed_token(clean_mssv)
            feed_dict = build_student_calendar_feed(clean_mssv, tok)
            ics_text = feed_dict.get("ics", "")

            self.assertIn("BEGIN:VCALENDAR", ics_text)
            self.assertIn("Toán cao cấp", ics_text)
            # Assert student MSSV is NOT anywhere inside the .ics feed content
            self.assertNotIn(clean_mssv, ics_text, "Generated ICS feed must be free of raw MSSV")
        finally:
            self._cleanup(clean_mssv)

    def test_public_config_endpoint(self):
        """Phase 2.4: /api/public-config must be publicly accessible and expose strictly 3 fields."""
        res = self.client.get("/api/public-config")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Cache-Control", res.headers)
        self.assertIn("public", res.headers["Cache-Control"])
        self.assertIn("max-age=300", res.headers["Cache-Control"])

        data = res.get_json()
        self.assertIsInstance(data, dict)
        # Contains allowed public fields including version
        expected_keys = {"contact_email", "repo_url", "auto_sync_template_url", "version"}
        self.assertEqual(set(data.keys()), expected_keys)


if __name__ == "__main__":
    unittest.main()
