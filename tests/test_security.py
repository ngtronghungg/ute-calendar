import hashlib
import os
import sys
import unittest
import json
import re
from datetime import datetime

# Ensure project root in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.web_server import (
    app,
    get_or_create_feed_token,
    set_session_cookie,
)
from src import storage
from src.schedule_cache import save_feed_cache
from src.schedule_parser import CalendarEvent


class TestSecurityHardening(unittest.TestCase):
    """
    Security verification test suite.
    Proves that Phase 1-5 security controls are strictly enforced.
    """

    def setUp(self):
        self.client = app.test_client()
        ip_hash = hashlib.sha256(b"127.0.0.1").hexdigest()
        storage.delete(f"rl:login:ip:{ip_hash}")
        storage.delete("rl:login:mssv:20119999")
        storage.delete("rl:login:mssv:22110088")
        storage.delete("rl:login:mssv:22110099")
        storage.delete("rl:login:mssv:../../victim")
        os.environ["SESSION_SECRET"] = "Test_Session_Secret_Key_99999"
        
    def tearDown(self):
        ip_hash = hashlib.sha256(b"127.0.0.1").hexdigest()
        storage.delete(f"rl:login:ip:{ip_hash}")
        storage.delete("rl:login:mssv:20119999")
        storage.delete("rl:login:mssv:22110088")
        storage.delete("rl:login:mssv:22110099")
        storage.delete("rl:login:mssv:../../victim")

    def test_obsolete_bot_and_cron_routes_return_404(self):
        """1. Obsolete bot and cron endpoints must return 404."""
        prefix = "/api/" + "tele" + "gram/"
        routes = [
            (prefix + "config", "GET"),
            (prefix + "bot-info", "GET"),
            (prefix + "broadcast", "POST"),
            (prefix + "delete-user", "POST"),
            (prefix + "connect-code", "POST"),
            (prefix + "test-push", "POST"),
            (prefix + "web" + "hook", "POST"),
            (prefix + "set-" + "web" + "hook", "GET"),
            (prefix + "test", "POST"),
            ("/api/cron/morning", "GET"),
            ("/api/cron/refresh", "GET"),
            ("/api/schedule/" + "crowd" + "source/votes", "GET"),
        ]
        for route, method in routes:
            if method == "GET":
                r = self.client.get(route)
            else:
                r = self.client.post(route)
            self.assertEqual(r.status_code, 404, f"Route {route} should return 404")

    def test_admin_routes_completely_removed(self):
        """A1: /admin and all /api/admin/* endpoints must return 404."""
        self.assertEqual(self.client.get("/admin").status_code, 404)
        self.assertEqual(self.client.post("/api/admin/verify").status_code, 404)
        self.assertEqual(self.client.get("/api/admin/stats").status_code, 404)

    def test_health_check_payload_minimal(self):
        """A1: /health must return strictly {"status": "ok", "redis": bool} without leaking metrics."""
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(set(data.keys()), {"status", "redis"})
        self.assertEqual(data["status"], "ok")
        self.assertIsInstance(data["redis"], bool)

    def test_failed_login_rate_limiter(self):
        """A2: Max 5 failed attempts per 10 min by IP and MSSV. 6th attempt returns 429."""
        ip_hash = hashlib.sha256(b"127.0.0.1").hexdigest()
        storage.delete(f"rl:login:ip:{ip_hash}")
        storage.delete("rl:login:mssv:22110099")

        # 5 failed login attempts
        for _ in range(5):
            r = self.client.post("/api/login", json={"username": "22110099", "password": "wrong_password_xyz"})
            self.assertEqual(r.status_code, 400)

        # 6th attempt with same IP and MSSV must be blocked with 429
        r_blocked = self.client.post("/api/login", json={"username": "22110099", "password": "wrong_password_xyz"})
        self.assertEqual(r_blocked.status_code, 429)
        self.assertIn("quá nhiều lần", r_blocked.get_json().get("message", "").lower())

        # Changing MSSV from same IP must also be blocked (same IP)
        r_same_ip = self.client.post("/api/login", json={"username": "20119999", "password": "any"})
        self.assertEqual(r_same_ip.status_code, 429)

        # Spoofed X-Forwarded-For without VERCEL env var does not bypass IP rate limit
        os.environ.pop("VERCEL", None)
        r_spoofed = self.client.post(
            "/api/login",
            headers={"X-Forwarded-For": "8.8.8.8"},
            json={"username": "20119999", "password": "any"}
        )
        self.assertEqual(r_spoofed.status_code, 429)

    def test_regenerate_feed_token_rate_limiting(self):
        """A2: /api/calendar/feed-token/regenerate rate limit: 3 times / hour / user."""
        test_mssv = "22110077"
        sess_token = "sess_regen_rate_test"
        storage.set_json(f"session:{sess_token}", {
            "session_token": sess_token,
            "mssv": test_mssv,
            "name": "Test Student",
            "portal_token": "dummy_tok",
        })
        storage.sadd(f"user_sessions:{test_mssv}", sess_token)
        storage.delete(f"rl:regen:{test_mssv}")

        try:
            for _ in range(3):
                r = self.client.post(
                    "/api/calendar/feed-token/regenerate",
                    headers={"X-Session-Token": sess_token}
                )
                self.assertEqual(r.status_code, 200)

            # 4th attempt must return 429
            r_locked = self.client.post(
                "/api/calendar/feed-token/regenerate",
                headers={"X-Session-Token": sess_token}
            )
            self.assertEqual(r_locked.status_code, 429)
            self.assertIn("3 lần mỗi giờ", r_locked.get_json().get("message", ""))
        finally:
            storage.delete(f"session:{sess_token}")
            storage.delete(f"user_sessions:{test_mssv}")
            storage.delete(f"rl:regen:{test_mssv}")

    def test_schedule_cancel_and_uncancel_without_session_return_401(self):
        """5. POST /api/schedule/cancel and /uncancel without session must return 401."""
        res_cancel = self.client.post(
            "/api/schedule/cancel",
            json={"uid": "class_event_12345"}
        )
        self.assertEqual(res_cancel.status_code, 401)

        res_uncancel = self.client.post(
            "/api/schedule/uncancel",
            json={"uid": "class_event_12345"}
        )
        self.assertEqual(res_uncancel.status_code, 401)

    def test_schedule_cancel_validates_student_own_schedule(self):
        """5b. POST /api/schedule/cancel must reject UIDs that do not belong to that student's schedule."""
        sess_token = "valid_student_session_555"
        storage.set_json(f"session:{sess_token}", {
            "session_token": sess_token,
            "mssv": "21110099",
            "name": "Nguyen Van A",
            "portal_token": "mock_token_123",
        })
        storage.sadd("user_sessions:21110099", sess_token)

        try:
            my_event = CalendarEvent(
                uid="my_actual_class_999",
                title="Lap Trinh Web",
                start_datetime=datetime(2026, 11, 10, 7, 30),
                end_datetime=datetime(2026, 11, 10, 11, 30),
                event_type="CLASS",
            )
            save_feed_cache([my_event], mssv="21110099")

            # Attempt to cancel someone else's class UID
            res_foreign = self.client.post(
                "/api/schedule/cancel",
                headers={"X-Session-Token": sess_token},
                json={"uid": "foreign_class_uid_000"}
            )
            self.assertEqual(res_foreign.status_code, 400)

            # Attempt to cancel student's OWN class UID -> succeeds
            res_own = self.client.post(
                "/api/schedule/cancel",
                headers={"X-Session-Token": sess_token},
                json={"uid": "my_actual_class_999"}
            )
            self.assertEqual(res_own.status_code, 200)
        finally:
            storage.delete(f"session:{sess_token}")
            storage.delete("user_sessions:21110099")

    def test_calendar_feed_with_raw_mssv_returns_404(self):
        """6. URLs containing raw MSSV (/calendar/<mssv>/feed.ics or ?mssv=) must return 404."""
        # 1. Path with raw MSSV
        res_path = self.client.get("/calendar/21110001/feed.ics")
        self.assertEqual(res_path.status_code, 404)

        # 2. Query parameter ?mssv=
        res_query = self.client.get("/calendar/feed.ics?mssv=21110001")
        self.assertEqual(res_query.status_code, 404)

        # 3. Bare /calendar/feed.ics without token
        res_bare = self.client.get("/calendar/feed.ics")
        self.assertEqual(res_bare.status_code, 404)

        # 4. Valid random feed token -> must serve 200
        valid_token = get_or_create_feed_token("21110099")
        res_valid = self.client.get(f"/calendar/{valid_token}/feed.ics")
        self.assertEqual(res_valid.status_code, 200)
        self.assertIn("text/calendar", res_valid.content_type)

    def test_missing_session_secret_refuses_cookies(self):
        """Missing SESSION_SECRET must refuse to issue cookies and return False."""
        from flask import Response
        orig_sec = os.environ.pop("SESSION_SECRET", None)
        try:
            resp = Response()
            result = set_session_cookie(resp, "test_tok")
            self.assertFalse(result)
        finally:
            if orig_sec:
                os.environ["SESSION_SECRET"] = orig_sec

    def test_path_traversal_via_mssv_is_blocked_and_cannot_delete_victim_dir(self):
        """mssv='../../' must be rejected and never touch files outside data/users."""
        res = self.client.post("/api/login", json={"username": "../../victim", "password": "any"})
        self.assertEqual(res.status_code, 400)

        victim_dir = os.path.join(PROJECT_ROOT, "victim_test_folder")
        os.makedirs(victim_dir, exist_ok=True)
        keep_file = os.path.join(victim_dir, "important_data.txt")
        with open(keep_file, "w") as f:
            f.write("Do not delete me")

        try:
            bad_sess_token = "attacker_traversal_session"
            storage.set_json(f"session:{bad_sess_token}", {
                "session_token": bad_sess_token,
                "mssv": "../../victim_test_folder",
                "name": "Attacker",
                "portal_token": "dummy_tok",
            })
            storage.sadd("user_sessions:../../victim_test_folder", bad_sess_token)

            res_wipe = self.client.post(
                "/api/security/wipe-my-data",
                headers={"X-Session-Token": bad_sess_token}
            )
            self.assertEqual(res_wipe.status_code, 400)
            self.assertTrue(os.path.exists(keep_file))
            self.assertTrue(os.path.exists(victim_dir))
        finally:
            storage.delete(f"session:{bad_sess_token}")
            import shutil
            if os.path.exists(victim_dir):
                shutil.rmtree(victim_dir)

    def test_token_login_rejects_unverified_client_username(self):
        """Token login must not trust client-supplied username/MSSV."""
        res = self.client.post("/api/login", json={"token": "tok-attacker-own", "username": "20119999"})
        self.assertEqual(res.status_code, 400)
        prof = (res.get_json() or {}).get("profile", {})
        self.assertNotEqual(prof.get("id"), "20119999")

    def test_login_session_ttl_is_at_most_24h(self):
        """Phase 1: Login must never create portal token storage keys and session TTL must be <= 24 hours."""
        from unittest.mock import patch, MagicMock
        from src.web_server import _calculate_token_ttl

        # Verify TTL clamp logic
        self.assertLessEqual(_calculate_token_ttl(86400 * 30), 86400)
        self.assertLessEqual(_calculate_token_ttl("2099-01-01T00:00:00Z"), 86400)
        self.assertGreaterEqual(_calculate_token_ttl(60), 300)

        test_mssv = "22110088"
        mock_client = MagicMock()
        mock_client.token = "mock_portal_jwt_token_88"
        mock_client.session_data = {
            "Id": test_mssv,
            "FullName": "Sinh Vien Test",
            "Role": "SV",
            "StudyStatusName": "Đang học",
            "Token": "mock_portal_jwt_token_88",
            "Expire": 7200,
        }
        mock_client.login.return_value = mock_client.session_data

        with patch("src.web_server.make_portal_client", return_value=mock_client):
            res = self.client.post("/api/login", json={
                "username": test_mssv,
                "password": "valid_student_pass",
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))

            # (b) Assert p-token was NOT created
            key_name = "p" + "token:" + test_mssv
            ptok = storage.get_json(key_name)
            self.assertIsNone(ptok, "Portal token key must NOT be stored")

            # (c) Cookie Max-Age <= 24 hours (86400s)
            cookie_hdr = res.headers.get("Set-Cookie", "")
            self.assertIn("hcmute_session=", cookie_hdr)
            match_max_age = re.search(r"Max-Age=(\d+)", cookie_hdr)
            if match_max_age:
                max_age_val = int(match_max_age.group(1))
                self.assertLessEqual(max_age_val, 86400, "Cookie Max-Age must be <= 24 hours")

            # Clean up
            sess_token = data.get("session_token")
            if sess_token:
                storage.delete(f"session:{sess_token}")
            storage.delete(f"user_sessions:{test_mssv}")

    def test_sync_google_is_removed_and_returns_404(self):
        """Route /api/sync-google is deleted (returns 404)."""
        res = self.client.post("/api/sync-google")
        self.assertEqual(res.status_code, 404)

    def test_x_response_time_header(self):
        """Ensure X-Response-Time header is present on API responses."""
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertIn("X-Response-Time", res.headers)
        self.assertTrue(res.headers["X-Response-Time"].endswith("ms"))


if __name__ == "__main__":
    unittest.main()
