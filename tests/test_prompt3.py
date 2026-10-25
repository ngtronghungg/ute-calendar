import os
import re
import unittest
from html.parser import HTMLParser
from src.web_server import app


class SimpleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class TestPrompt3GoogleLoginRemovalAndLoginView(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_google_login_route_returns_404(self):
        """POST /api/login/google must return 404 Not Found."""
        res = self.client.post("/api/login/google", json={})
        self.assertEqual(res.status_code, 404)

        res2 = self.client.post("/api/login/google", json={"credential": "xyz"})
        self.assertEqual(res2.status_code, 404)

    def test_no_forbidden_google_auth_references_in_codebase(self):
        """
        Verify forbidden auth endpoint names and Google gsi script
        are completely removed from src/, public/, and tests/.
        """
        forbidden = [
            "Authenticate" + "Google",
            "login_with_" + "google",
            "accounts.google." + "com/gsi",
        ]
        target_dirs = ["src", "public", "tests"]
        matches = []

        for d in target_dirs:
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith((".pyc", ".png", ".svg", ".ico")):
                        continue
                    if f == "test_prompt3.py":
                        continue
                    file_path = os.path.join(root, f)
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                            for idx, line in enumerate(fp, 1):
                                for pattern in forbidden:
                                    if pattern.lower() in line.lower():
                                        matches.append(f"{file_path}:{idx}: {line.strip()}")
                    except Exception:
                        pass

        self.assertEqual(matches, [], f"Found forbidden Google login patterns:\n" + "\n".join(matches))

    def test_login_view_texts_and_link(self):
        """
        Verify #loginView has:
        - Line 1: 'Thường đăng nhập cổng trường bằng Google? Bạn cần có mật khẩu cổng trường để dùng UTE-Calendar. Bấm Quên mật khẩu ở cổng trường để đặt một lần.'
          with 'Quên mật khẩu ở cổng trường' linking to https://online.hcmute.edu.vn with target='_blank' rel='noopener noreferrer'.
        - Line 2: 'UTE-Calendar dành cho sinh viên HCMUTE.'
        - Link 'Chỉ muốn lịch tự cập nhật? Xem cách cài' remains below.
        - No Google references in the login form/notices.
        """
        with open("public/index.html", "r", encoding="utf-8") as f:
            html = f.read()

        # Find loginView block
        m = re.search(r'<div\s+id="loginView"[^>]*>(.*?)<!--\s*(?:2\.\s*)?GUEST SYNC VIEW', html, re.DOTALL)
        self.assertIsNotNone(m, "Could not find #loginView section")
        login_view_html = m.group(1)

        # Check exact strings
        line1_text = (
            "Thường đăng nhập cổng trường bằng Google? "
            "Bạn cần có mật khẩu cổng trường để dùng UTE-Calendar. "
            "Bấm"
        )
        line1_end = "để đặt một lần."
        self.assertIn(line1_text, login_view_html)
        self.assertIn(line1_end, login_view_html)

        line2_text = "UTE-Calendar dành cho sinh viên HCMUTE."
        self.assertIn(line2_text, login_view_html)

        # Check link for online.hcmute.edu.vn
        link_match = re.search(
            r'<a\s+[^>]*href=["\']https://online\.hcmute\.edu\.vn["\'][^>]*>(.*?)</a>',
            login_view_html,
            re.DOTALL
        )
        self.assertIsNotNone(link_match, "Link to online.hcmute.edu.vn not found")
        link_tag = link_match.group(0)
        self.assertIn('target="_blank"', link_tag)
        self.assertIn('rel="noopener noreferrer"', link_tag)
        self.assertEqual(link_match.group(1).strip(), "Quên mật khẩu ở cổng trường")

        # Check existing guest sync link is still present
        self.assertIn("Chỉ muốn lịch tự cập nhật? Xem cách cài", login_view_html)

        # Ensure no "đăng nhập qua Google" remains in login notice callout or forms
        self.assertNotIn("đăng nhập qua Google", login_view_html)

    def test_faq_has_8_items_with_new_questions(self):
        """
        Verify public/faq.html has exactly 8 items, with the two new questions
        for Google login users and lecturers.
        """
        with open("public/faq.html", "r", encoding="utf-8") as f:
            html = f.read()

        faq_items = re.findall(r'<details\s+class="faq-item">(.*?)</details>', html, re.DOTALL)
        self.assertEqual(len(faq_items), 8, f"Expected 8 FAQ items, found {len(faq_items)}")

        # Item 7
        self.assertIn("Tôi đăng nhập cổng trường bằng Google thì dùng UTE-Calendar thế nào?", faq_items[6])
        self.assertIn(
            "Bạn cần có mật khẩu cổng trường. Mở cổng trường, bấm Quên mật khẩu và đặt mật khẩu một lần. "
            "Sau đó đăng nhập UTE-Calendar bằng mã số sinh viên và mật khẩu đó.",
            faq_items[6]
        )

        # Item 8
        self.assertIn("Giảng viên dùng được không?", faq_items[7])
        self.assertIn(
            "Hiện chưa. UTE-Calendar chỉ đọc được thời khoá biểu và lịch thi của sinh viên.",
            faq_items[7]
        )


if __name__ == "__main__":
    unittest.main()
