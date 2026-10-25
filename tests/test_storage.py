import os
import sys
import unittest
import time
import requests
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.storage as storage


class TestStorage(unittest.TestCase):
    def setUp(self):
        os.environ["SESSION_SECRET"] = "test-session-secret-key-32chars"
        # Ensure clean state per test
        storage.delete("test:k1")
        storage.delete("test:nx")
        storage.delete("test:set")

    def tearDown(self):
        storage.delete("test:k1")
        storage.delete("test:nx")
        storage.delete("test:set")

    def test_local_json_crud_and_ttl(self):
        # Default value when not found
        self.assertEqual(storage.get_json("test:k1", default="def"), "def")

        # Set and get
        obj = {"a": 1, "b": "hello", "nested": [1, 2, 3]}
        self.assertTrue(storage.set_json("test:k1", obj))
        self.assertEqual(storage.get_json("test:k1"), obj)

        # Delete
        storage.delete("test:k1")
        self.assertIsNone(storage.get_json("test:k1"))

        # TTL expiry
        storage.set_json("test:k1", "expiring", ttl=1)
        self.assertEqual(storage.get_json("test:k1"), "expiring")
        time.sleep(1.1)
        self.assertIsNone(storage.get_json("test:k1"))

    def test_set_nx_idempotency(self):
        # 1st call should succeed (key does not exist)
        self.assertTrue(storage.set_nx("test:nx", "first_val", ttl=10))
        # 2nd call should return False (key already exists)
        self.assertFalse(storage.set_nx("test:nx", "second_val", ttl=10))

    def test_set_operations_sadd_scard_smembers_srem(self):
        self.assertEqual(storage.scard("test:set"), 0)
        self.assertEqual(storage.smembers("test:set"), set())

        # Add member 1
        self.assertEqual(storage.sadd("test:set", "user_1"), 1)
        # Adding same member again returns 0
        self.assertEqual(storage.sadd("test:set", "user_1"), 0)

        # Add member 2
        self.assertEqual(storage.sadd("test:set", "user_2"), 1)

        self.assertEqual(storage.scard("test:set"), 2)
        self.assertEqual(storage.smembers("test:set"), {"user_1", "user_2"})

        # Remove member 1
        self.assertEqual(storage.srem("test:set", "user_1"), 1)
        self.assertEqual(storage.scard("test:set"), 1)
        self.assertEqual(storage.smembers("test:set"), {"user_2"})

        # Removing non-member returns 0
        self.assertEqual(storage.srem("test:set", "user_1"), 0)

    @patch("requests.Session.post")
    def test_upstash_redis_rest_calls(self, mock_post):
        # Mock Upstash environment variables
        os.environ["UPSTASH_REDIS_REST_URL"] = "https://mock-redis.upstash.io"
        os.environ["UPSTASH_REDIS_REST_TOKEN"] = "mock_token_123"

        try:
            # 1. Test get_json calls Redis with ["GET", key]
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"result": '{"foo": "bar"}'}
            mock_post.return_value = mock_resp

            res = storage.get_json("test:redis_key")
            self.assertEqual(res, {"foo": "bar"})
            mock_post.assert_called_with(
                "https://mock-redis.upstash.io",
                headers={
                    "Authorization": "Bearer mock_token_123",
                    "Content-Type": "application/json",
                },
                json=["GET", "test:redis_key"],
                timeout=3.0,
            )

            # 2. Test set_json calls Redis with ["SET", key, val, "EX", ttl]
            mock_resp.json.return_value = {"result": "OK"}
            storage.set_json("test:redis_key", {"foo": "bar"}, ttl=3600)
            mock_post.assert_called_with(
                "https://mock-redis.upstash.io",
                headers={
                    "Authorization": "Bearer mock_token_123",
                    "Content-Type": "application/json",
                },
                json=["SET", "test:redis_key", '{"foo": "bar"}', "EX", 3600],
                timeout=3.0,
            )

            # 3. Test Redis exception does not raise into handler
            mock_post.side_effect = requests.exceptions.Timeout("Redis timeout")
            safe_val = storage.get_json("test:timeout_key", default="fallback")
            # Must return without raising
            self.assertEqual(safe_val, "fallback")

        finally:
            os.environ.pop("UPSTASH_REDIS_REST_URL", None)
            os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

    def test_session_lifecycle(self):
        """Verify session:<id> stored with TTL and cookie holds ONLY random session id."""
        from src.web_server import app, set_session_cookie, get_request_session
        from flask import Response

        session_id = "test_rand_sid_99887766"
        mssv = "21110099"
        session_data = {
            "session_token": session_id,
            "mssv": mssv,
            "name": "Test Student",
            "portal_token": "tok_xyz_123",
            "expire": 3600,
        }

        storage.set_json(f"session:{session_id}", session_data, ttl=7200)
        storage.sadd(f"user_sessions:{mssv}", session_id)

        # Verify session can be retrieved
        fetched = storage.get_json(f"session:{session_id}")
        self.assertEqual(fetched.get("mssv"), mssv)
        self.assertEqual(fetched.get("portal_token"), "tok_xyz_123")

        # Verify Cookie holds ONLY that session id
        with app.test_request_context():
            resp = Response()
            set_session_cookie(resp, session_id)
            cookie_hdr = resp.headers.get("Set-Cookie", "")
            self.assertIn(f"hcmute_session={session_id}", cookie_hdr)
            # Must NOT contain user data or portal_token
            self.assertNotIn("portal_token", cookie_hdr)
            self.assertNotIn("tok_xyz_123", cookie_hdr)
            self.assertNotIn("Test Student", cookie_hdr)

        # Clean up
        storage.delete(f"session:{session_id}")
        storage.delete(f"user_sessions:{mssv}")

    def test_personal_cancellations_using_sets(self):
        """Phase 2 & 3: Cancellations must use personal atomic sets (sadd/srem/smembers)."""
        from src.schedule_state import add_cancellation, remove_cancellation, load_cancellations

        class_uid = "hcmute_class_cs101_test"
        mssv = "21110011"

        # Initially no cancellations
        self.assertEqual(len(load_cancellations(mssv)), 0)

        # Student cancels
        add_cancellation(mssv, class_uid)
        cancellations = load_cancellations(mssv)
        self.assertIn(class_uid, cancellations)

        # Other student is unaffected
        self.assertEqual(len(load_cancellations("21110022")), 0)

        # Student restores class
        remove_cancellation(mssv, class_uid)
        self.assertNotIn(class_uid, load_cancellations(mssv))

    def test_hosted_mode_skips_secrets_file(self):
        """Phase 3: Hosted mode reads secrets from env only (never data/.secrets.json)."""
        from src.app_config import load_config, BASE_DATA_DIR

        try:
            os.environ["HOSTED_MODE"] = "1"
            os.environ["CONTACT_EMAIL"] = "env_contact@example.com"

            cfg = load_config(force_reload=True)
            self.assertEqual(cfg.get("contact_email"), "env_contact@example.com")
        finally:
            os.environ.pop("HOSTED_MODE", None)
            os.environ.pop("CONTACT_EMAIL", None)


if __name__ == "__main__":
    unittest.main()
