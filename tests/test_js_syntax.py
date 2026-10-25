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


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("path", JS_FILES, ids=[os.path.basename(p) for p in JS_FILES])
def test_public_js_has_valid_syntax(path):
    result = subprocess.run(
        ["node", "--check", path], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
