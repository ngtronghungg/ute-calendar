"""Frontend JavaScript must parse: a syntax error silently disables the whole page."""
import glob
import os
import shutil
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
JS_FILES = sorted(
    p for p in glob.glob(os.path.join(ROOT, "public", "*.js"))
)


def _read(name):
    with open(os.path.join(ROOT, "public", name), encoding="utf-8") as f:
        return f.read()


def test_every_data_action_has_a_handler():
    import re

    html, js = _read("index.html"), _read("app.js")
    used = set(re.findall(r'data-action="([a-z0-9-]+)"', html + js))
    handled = set(re.findall(r"case '([a-z0-9-]+)'", js))
    assert used, "no data-action found"
    assert not (used - handled), f"actions without a handler: {sorted(used - handled)}"


def test_js_does_not_depend_on_inline_handler_attributes():
    js = _read("app.js")
    assert "getAttribute('onclick')" not in js
    assert 'getAttribute("onclick")' not in js


def test_js_toggles_visibility_with_the_hidden_class_only():
    # ui.css defines `.hidden { display: none !important }`, so `style.display = ...`
    # can never reveal an element that carries that class.
    js = _read("app.js")
    assert "style.display" not in js, "use classList.add/remove('hidden') instead"


def test_auto_sync_card_always_shows_a_button_or_a_notice():
    html = _read("index.html")
    assert 'id="btnToggleAutoGuide"' in html
    assert 'id="autoSyncPrepNotice"' in html
    assert "Tính năng này đang được chuẩn bị." in html


def test_every_tab_button_matches_a_tab_panel():
    import re

    html = _read("index.html")
    tabs = re.findall(r'data-action="switch-tab" data-tab="([a-z]+)"', html)
    assert tabs, "no tab buttons"
    for name in tabs:
        assert f'id="{name}Tab"' in html, f"missing panel for tab {name}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("path", JS_FILES, ids=[os.path.basename(p) for p in JS_FILES])
def test_public_js_has_valid_syntax(path):
    result = subprocess.run(
        ["node", "--check", path], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
