"""
Unit tests for Strict Content Security Policy (CSP), zero-inline markup, and cache headers.
"""

import os
import re
import pytest
from src.web_server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_html_files_zero_inline_scripts():
    """All public HTML files must have strictly zero inline script content."""
    public_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "public"))
    html_files = [os.path.join(public_dir, f) for f in os.listdir(public_dir) if f.endswith(".html")]
    assert len(html_files) >= 3

    for fpath in html_files:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        # Match script tags that don't have a src attribute or have inline text
        scripts = re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", content, re.DOTALL | re.IGNORECASE)
        for s in scripts:
            assert not s.strip(), f"Found inline script in {os.path.basename(fpath)}: {s[:100]}"


def test_html_files_zero_inline_event_handlers():
    """All public HTML files must have strictly zero inline on* handlers (e.g. onclick)."""
    public_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "public"))
    html_files = [os.path.join(public_dir, f) for f in os.listdir(public_dir) if f.endswith(".html")]

    for fpath in html_files:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        handlers = re.findall(r"\bon[a-z]+\s*=", content, re.IGNORECASE)
        assert len(handlers) == 0, f"Found inline handlers in {os.path.basename(fpath)}: {handlers}"


def test_html_files_zero_inline_styles():
    """All public HTML files must have strictly zero inline style attributes."""
    public_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "public"))
    html_files = [os.path.join(public_dir, f) for f in os.listdir(public_dir) if f.endswith(".html")]

    for fpath in html_files:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        styles = re.findall(r'(?<![-a-zA-Z0-9])style\s*=\s*["\'][^"\']*["\']', content, re.IGNORECASE)
        assert len(styles) == 0, f"Found inline style attributes in {os.path.basename(fpath)}: {styles[:5]}"


def test_strict_csp_header(client):
    """Server responses must enforce strict CSP without 'unsafe-inline' in script-src and style-src."""
    res = client.get("/")
    assert "Content-Security-Policy" in res.headers
    csp = res.headers["Content-Security-Policy"]

    # Verify directives
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp

    # Scripts and stylesheets stay strict. The ONLY relaxation is inline style ATTRIBUTES
    # (style="...") used by JS-rendered cards; never <style> elements or inline scripts.
    directives = {d.strip().split(" ", 1)[0]: d.strip() for d in csp.split(";") if d.strip()}
    assert "'unsafe-inline'" not in directives["script-src"]
    assert "'unsafe-inline'" not in directives["style-src"]
    assert "'unsafe-eval'" not in csp
    unsafe = [name for name, value in directives.items() if "'unsafe-inline'" in value]
    assert unsafe in ([], ["style-src-attr"])


def test_static_cache_headers(client):
    """Static assets must serve Cache-Control: public, max-age=0, must-revalidate."""
    res = client.get("/ui.css")
    assert res.status_code == 200
    cache_ctrl = res.headers.get("Cache-Control", "")
    assert "public" in cache_ctrl
    assert "max-age=0" in cache_ctrl
    assert "must-revalidate" in cache_ctrl
