"""The no-password path: text copied from the portal's "Xem thời khóa biểu" table becomes an .ics in the browser."""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SAMPLE = os.path.join(ROOT, "tests", "fixtures", "portal_timetable_paste.txt")
CORE = os.path.join(ROOT, "public", "paste-core.js")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

SCRIPT = """
const core = require(process.argv[1]);
const text = require('fs').readFileSync(process.argv[2], 'utf8');
const parsed = core.parseTimetable(text);
const ics = core.buildIcs(parsed.courses, new Date('2026-10-26T00:00:00Z'));
console.log(JSON.stringify({ parsed, ics }));
"""


@pytest.fixture(scope="module")
def result():
    out = subprocess.run(
        ["node", "-e", SCRIPT, CORE, SAMPLE], capture_output=True, text=True, timeout=30, encoding="utf-8"
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_reads_every_course_with_a_schedule(result):
    courses = {c["code"]: c for c in result["parsed"]["courses"]}
    assert len(courses) == 9  # the thesis row has no schedule and is reported, not invented
    assert courses["HYPN221129"]["name"] == "Kỹ thuật thủy lực - khí nén"
    assert courses["EEEI321925"]["name"] == "Trang bị điện-điện tử trong máy công nghiệp"
    assert any("Đồ án" in w for w in result["parsed"]["warnings"])


def test_continuation_rows_belong_to_the_previous_course(result):
    courses = {c["code"]: c for c in result["parsed"]["courses"]}
    assert len(courses["HYPN221129"]["sessions"]) == 2
    assert len(courses["MTNC340925"]["sessions"]) == 3
    assert len(courses["EEEI321925"]["sessions"]) == 4


def test_week_counts_and_dates(result):
    courses = {c["code"]: c for c in result["parsed"]["courses"]}
    metal = courses["METE230130"]["sessions"][0]
    assert (metal["firstDate"], metal["count"], metal["dow"]) == ("2026-11-02", 9, 0)
    assert (metal["hour"], metal["minute"], metal["room"]) == (7, 30, "A108")
    one_day = courses["HYPN221129"]["sessions"][0]
    assert (one_day["firstDate"], one_day["count"]) == ("2026-12-22", 1)


def test_period_estimate_matches_the_weekly_view_the_portal_showed(result):
    courses = {c["code"]: c for c in result["parsed"]["courses"]}
    assert courses["METE230130"]["periods"] == 5  # portal weekly view: Tiết 1->5
    assert courses["LLCT220514"]["periods"] == 4  # portal weekly view: Tiết 7->10


def test_ics_is_well_formed(result):
    ics = result["ics"]
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == ics.count("END:VEVENT") == 18  # one weekly series per table row
    assert "DTSTART;TZID=Asia/Ho_Chi_Minh:20261102T073000" in ics
    assert "DTEND;TZID=Asia/Ho_Chi_Minh:20261102T113000" in ics
    assert "RRULE:FREQ=WEEKLY;COUNT=9" in ics
    for line in ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75


def test_page_is_wired_and_does_not_need_the_server():
    with open(os.path.join(ROOT, "public", "dan-lich.html"), encoding="utf-8") as f:
        html = f.read()
    assert "paste-core.js" in html and "paste.js" in html
    for name in ("paste-core.js", "paste.js"):
        with open(os.path.join(ROOT, "public", name), encoding="utf-8") as f:
            js = f.read()
        assert "fetch(" not in js and "XMLHttpRequest" not in js and "sendBeacon" not in js
        assert "innerHTML" not in js
