"""
Application Configuration and Environment Utilities
Provides lightweight configuration loading, and Vietnam timezone handling.
"""

import os
import sys
import json
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE_DATA_DIR = os.environ.get("DATA_DIR", "/tmp/data" if os.environ.get("VERCEL") else os.path.join(PROJECT_ROOT, "data"))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "config.json")

# Standard Vietnam Timezone (UTC+7 / ICT / Asia/Ho_Chi_Minh)
VIETNAM_TZ = timezone(timedelta(hours=7))

_CONFIG_CACHE = None
_CONFIG_CACHE_MTIME = 0.0
_SECRETS_CACHE_MTIME = 0.0
_CONFIG_CACHE_LOCK = threading.Lock()


def get_vietnam_now() -> datetime:
    """Return current datetime strictly in Vietnam Timezone (UTC+7)."""
    return datetime.now(timezone.utc).astimezone(VIETNAM_TZ).replace(tzinfo=None)


def is_hosted_mode() -> bool:
    """Check if application is running in hosted cloud / serverless environment."""
    from src import storage
    return bool(
        os.environ.get("VERCEL")
        or os.environ.get("RENDER")
        or os.environ.get("HOSTED_MODE")
        or storage.is_redis_available()
    )


def load_config(force_reload: bool = False) -> dict:
    """Load configuration containing general settings."""
    global _CONFIG_CACHE, _CONFIG_CACHE_MTIME, _SECRETS_CACHE_MTIME
    secrets_path = os.path.join(BASE_DATA_DIR, ".secrets.json")

    try:
        cfg_mtime = os.path.getmtime(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else 0.0
        sec_mtime = os.path.getmtime(secrets_path) if (not is_hosted_mode() and os.path.exists(secrets_path)) else 0.0
    except OSError:
        cfg_mtime, sec_mtime = 0.0, 0.0

    with _CONFIG_CACHE_LOCK:
        if not force_reload and _CONFIG_CACHE is not None and cfg_mtime == _CONFIG_CACHE_MTIME and sec_mtime == _SECRETS_CACHE_MTIME:
            return json.loads(json.dumps(_CONFIG_CACHE))

    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

    # Keep only general settings
    cfg = {k: v for k, v in cfg.items() if k in ("contact_email", "repo_url", "auto_sync_template_url")}

    # Read environment variables for general settings
    for env_k, cfg_k in [("CONTACT_EMAIL", "contact_email"), ("GITHUB_REPO_URL", "repo_url"), ("AUTO_SYNC_TEMPLATE_URL", "auto_sync_template_url")]:
        v = os.environ.get(env_k)
        if v:
            cfg[cfg_k] = v.strip()

    with _CONFIG_CACHE_LOCK:
        _CONFIG_CACHE = cfg
        _CONFIG_CACHE_MTIME = cfg_mtime
        _SECRETS_CACHE_MTIME = sec_mtime

    return json.loads(json.dumps(cfg))


def save_config(cfg: dict) -> bool:
    """Save config to local disk; strictly disabled in hosted/Vercel mode."""
    if is_hosted_mode():
        return False
    try:
        clean_cfg = {k: v for k, v in cfg.items() if k in ("contact_email", "repo_url", "auto_sync_template_url")}

        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(clean_cfg, f, ensure_ascii=False, indent=2)

        global _CONFIG_CACHE
        with _CONFIG_CACHE_LOCK:
            _CONFIG_CACHE = None
        return True
    except Exception:
        return False
