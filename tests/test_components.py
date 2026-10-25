"""
Test suite for UTE-Calendar Tool
"""

import unittest
from datetime import datetime
from src.schedule_parser import (
    parse_semester_schedule,
    parse_exam_schedule,
    parse_period_range,
    CalendarEvent,
)
from src.notice_analyzer import NoticeAnalyzer, extract_dates_from_text, ConsiderationItem
from src.ics_exporter import export_events_to_ics


class TestScheduleParser(unittest.TestCase):
    def test_period_parsing(self):
        self.assertEqual(parse_period_range("1-3"), (1, 3))
        self.assertEqual(parse_period_range("Tiết 7-9"), (7, 9))
        self.assertEqual(parse_period_range("10"), (10, 10))
        self.assertEqual(parse_period_range(5), (5, 5))

    def test_semester_schedule_parsing(self):
        sample_data = {
            "result": [
                {
                    "MaLHP": "MATH143001_01",
                    "TenHP": "Toán cao cấp 1",
                    "HoTenGV": "TS. Nguyễn Văn A",
                    "Phong": "A1-205",
                    "Thu": 2,  # Monday
                    "PeriodID": "1-3",
                    "BeginDate": "2026-09-07T00:00:00",
                    "EndDate": "2026-10-05T00:00:00",
                    "TuanHoc": "12345",
                    "CampusName": "Khu A",
                }
            ]
        }
        events, _ = parse_semester_schedule(sample_data)
        self.assertGreater(len(events), 0)
        ev = events[0]
        self.assertIn("Toán cao cấp 1", ev.title)
        self.assertIn("A1-205", ev.location)
        self.assertEqual(ev.start_datetime.hour, 7)
        self.assertEqual(ev.start_datetime.minute, 30)
        self.assertEqual(ev.end_datetime.hour, 9)
        self.assertEqual(ev.end_datetime.minute, 45)

    def test_exam_schedule_parsing(self):
        sample_exam = [
            {
                "MaHP": "MATH143001",
                "TenHP": "Toán cao cấp 1",
                "PhongThi": "A2-301",
                "NgayThi": "2026-12-15",
                "GioThi": "07:30",
                "ThoiGianLamBai": 90,
                "SBD": "105",
            }
        ]
        events, _ = parse_exam_schedule(sample_exam)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertIn("Thi: Toán cao cấp 1", ev.title)
        self.assertEqual(ev.start_datetime.hour, 7)
        self.assertEqual(ev.start_datetime.minute, 30)
        self.assertEqual(ev.end_datetime.hour, 9)
        self.assertEqual(ev.end_datetime.minute, 0)


class TestNoticeAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analyzer = NoticeAnalyzer()

    def test_extract_dates(self):
        text = "Hạn chót đóng học phí trước ngày 15/11/2026 vào lúc 17h00."
        dates = extract_dates_from_text(text)
        self.assertGreater(len(dates), 0)
        self.assertEqual(dates[0].year, 2026)
        self.assertEqual(dates[0].month, 11)
        self.assertEqual(dates[0].day, 15)
        self.assertEqual(dates[0].hour, 17)

    def test_tuition_notice_analysis(self):
        notice = {
            "MessageID": "1001",
            "MessageSubject": "Thông báo về việc đóng học phí Học kỳ 1 năm học 2026-2027",
            "MessageBody": "Sinh viên hoàn thành nghĩa vụ học phí trước ngày 25/11/2026 qua cổng VNPAY.",
            "CreationDate": "2026-10-15T08:00:00",
        }
        item = self.analyzer.analyze_announcement(notice)
        self.assertIsNotNone(item)
        self.assertEqual(item.category, "TUITION")
        self.assertEqual(item.priority, "HIGH")
        self.assertIsNotNone(item.deadline)
        self.assertEqual(item.deadline.day, 25)
        self.assertEqual(item.deadline.month, 11)

    def test_civic_education_notice_analysis(self):
        notice = {
            "MessageID": "1002",
            "MessageSubject": "Kế hoạch tổ chức Tuần sinh hoạt công dân đầu khóa năm học 2026-2027",
            "MessageBody": "Yêu cầu tân sinh viên tham gia và làm bài thu hoạch trực tuyến đến hết ngày 30/11/2026.",
            "CreationDate": "2026-10-10T08:00:00",
        }
        item = self.analyzer.analyze_announcement(notice)
        self.assertIsNotNone(item)
        self.assertEqual(item.category, "CIVIC_EDUCATION")
        self.assertEqual(item.priority, "HIGH")
        self.assertIn("Sinh hoạt công dân", item.title)

    def test_personal_message_preservation(self):
        """Ensure personal inbox messages from instructors without explicit future dates are never dropped."""
        personal_msg = {
            "MessageID": "2001",
            "MessageSubject": "Dặn dò ôn tập môn Cơ sở dữ liệu và nộp đề tài qua email",
            "MessageBody": "Các em gửi báo cáo bài tập lớn trước tuần 12 vào email thầy.",
            "SenderName": "TS. Trần Văn B",
            "CreationDate": "2026-10-18T10:00:00",
        }
        item = self.analyzer.analyze_announcement(personal_msg, notice_type="personal")
        self.assertIsNotNone(item)
        self.assertEqual(item.notice_type, "personal")
        self.assertEqual(item.sender, "TS. Trần Văn B")
        self.assertIn("Cơ sở dữ liệu", item.title)

    def test_general_announcement_preservation(self):
        """Ensure general university announcements without future deadlines are retained as informative notices."""
        general_notice = {
            "MaTin": "3001",
            "TieuDe": "Thông báo v/v Tổ chức Ngày hội việc làm và Kết nối Doanh nghiệp năm 2026",
            "NoiDung": "Phòng Quan hệ Doanh nghiệp kính mời các bạn sinh viên tham dự ngày hội.",
            "StaffName": "Phòng Tuyển sinh và Quan hệ Doanh nghiệp",
            "CreateDate": "2026-10-19T08:30:00",
        }
        item = self.analyzer.analyze_announcement(general_notice, notice_type="general")
        self.assertIsNotNone(item)
        self.assertEqual(item.notice_type, "general")
        self.assertIn("Ngày hội việc làm", item.title)
        self.assertEqual(item.sender, "Phòng Tuyển sinh và Quan hệ Doanh nghiệp")

    def test_ics_export(self):
        ev = CalendarEvent(
            uid="test-1",
            title="Kiểm thử sự kiện",
            start_datetime=datetime(2026, 11, 15, 7, 0),
            end_datetime=datetime(2026, 11, 15, 9, 30),
            location="Phòng A1-205",
            description="Mô tả sự kiện",
            event_type="CLASS",
        )
        ics_path = "data/test_output.ics"
        result = export_events_to_ics([ev], output_path=ics_path)
        self.assertTrue(result.endswith(".ics"))

    def test_health_check_endpoint(self):
        from src.web_server import app
        with app.test_client() as client:
            res = client.get("/health")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data.get("status"), "ok")
            self.assertIn("redis", data)

    def test_calendar_feed_with_exam_returns_200_and_vevent(self):
        """Prompt 1: GET /calendar/<token>/feed.ics with exam must return 200 without timedelta crash and contain BEGIN:VEVENT."""
        from src.web_server import app, get_or_create_feed_token
        from src.schedule_cache import save_cached_exams
        test_mssv = "12345678"
        exam_ev = CalendarEvent(
            uid="exam-12345678-test",
            title="Thi Cuối Kỳ Nhập Môn",
            start_datetime=datetime(2026, 12, 1, 7, 30),
            end_datetime=datetime(2026, 12, 1, 9, 30),
            location="Phòng A1-101",
            event_type="EXAM",
        )
        save_cached_exams([exam_ev], mssv=test_mssv)
        tok = get_or_create_feed_token(test_mssv)

        with app.test_client() as client:
            res = client.get(f"/calendar/{tok}/feed.ics")
            self.assertEqual(res.status_code, 200)
            data_str = res.get_data(as_text=True)
            self.assertIn("BEGIN:VCALENDAR", data_str)
            self.assertIn("BEGIN:VEVENT", data_str)
            self.assertIn("Thi Cuối Kỳ Nhập Môn", data_str)

    def test_static_svg_and_ui_css_served(self):
        """Phase 4.1 and 5.1: /logo-mark-white.svg, /favicon.svg, and /ui.css must return 200."""
        from src.web_server import app
        import json
        with app.test_client() as client:
            res_logo = client.get("/logo-mark-white.svg")
            self.assertEqual(res_logo.status_code, 200)
            self.assertIn("svg", res_logo.content_type.lower())

            res_fav = client.get("/favicon.svg")
            self.assertEqual(res_fav.status_code, 200)
            self.assertIn("svg", res_fav.content_type.lower())

            res_css = client.get("/ui.css")
            self.assertEqual(res_css.status_code, 200)

        with open("vercel.json", "r", encoding="utf-8") as f:
            v_cfg = json.load(f)
            for rw in v_cfg.get("rewrites", []):
                self.assertNotIn("svg", rw.get("source", ""))

    def test_export_ics_without_session_returns_401(self):
        """Prompt 1: POST /api/export-ics without authenticated session must return 401."""
        from src.web_server import app
        with app.test_client() as client:
            res = client.post("/api/export-ics", json={"include_classes": True})
            self.assertEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
