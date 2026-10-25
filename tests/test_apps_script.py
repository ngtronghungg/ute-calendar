"""Guards for the self-updating spreadsheet template (apps_script/)."""
import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AS_DIR = os.path.join(ROOT, "apps_script")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


CODE = _read(os.path.join(AS_DIR, "Code.gs"))


def test_version_matches_public_json():
    m = re.search(r'APPS_SCRIPT_VERSION\s*=\s*"([^"]+)"', CODE)
    assert m, "APPS_SCRIPT_VERSION missing"
    data = json.loads(_read(os.path.join(ROOT, "public", "apps_script_version.json")))
    assert data["version"] == m.group(1)


def test_update_url_points_at_our_own_site_not_a_made_up_domain():
    m = re.search(r'UPDATE_URL\s*=\s*"([^"]*)"', CODE)
    assert m and m.group(1), "UPDATE_URL missing"
    assert m.group(1).startswith("https://ute-calendar.vercel.app/")
    assert "ute-calendar.com" not in CODE


def test_menu_exposes_update_check():
    assert 'addItem("Kiểm tra bản mới", "checkForUpdatesMenu")' in CODE
    assert "function checkForUpdatesMenu" in CODE


def test_sync_is_guarded_against_bad_data():
    # Format validation and the mass-delete circuit breaker must actually be wired in.
    assert "validatePortalPayload(rawSchedule)" in CODE
    assert "diff.circuitBreakerTriggered" in CODE
    assert "maybeNotifyNewVersion(" in CODE


def test_failures_never_include_password_in_logs_or_emails():
    # Passwords may only be read from user properties and sent to the portal login call.
    for m in re.finditer(r"(console\.(log|warn|error)|Logger\.log|sendEmailNotification|emailOncePerDay)\([^;]*password", CODE):
        pytest.fail(f"password referenced in a log/email call: {m.group(0)[:80]}")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("name", ["Code", "Logic"])
def test_gs_files_parse(name):
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, f"{name}.js")
        shutil.copy(os.path.join(AS_DIR, f"{name}.gs"), target)
        result = subprocess.run(["node", "--check", target], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
