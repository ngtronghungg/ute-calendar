"""
HCMUTE Calendar & Reminder Sync - Local Web Server
Provides modern REST API and serves the Apple/Nothing-style Web UI.
"""

import os
import sys
import json
import base64
import hmac
import hashlib
import re
import secrets
import webbrowser
from threading import Timer
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _load_local_env() -> None:
    env_file = os.path.join(PROJECT_ROOT, ".env")
    if os.path.isfile(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


_load_local_env()

from flask import Flask, jsonify, request, send_file, send_from_directory, Response
import requests

from src.hcmute_api import HCMUTEClient, SessionExpired, make_portal_client
from src.branding import APP_NAME, APP_VERSION, APP_DISCLAIMER, DATA_TTL_DAYS, DATA_TTL_SECONDS
from src.schedule_parser import parse_semester_schedule, parse_exam_schedule, CalendarEvent, guess_current_term, get_available_years, make_expiry_event
from src.portal_schema import PortalFormatError
from src.notice_analyzer import NoticeAnalyzer
from src.ics_exporter import export_events_to_ics, events_to_ics_bytes
from src.app_config import load_config, save_config, get_vietnam_now, BASE_DATA_DIR, CONFIG_PATH
from src.schedule_state import (
    load_cancellations,
    add_cancellation,
    remove_cancellation,
    load_makeup_classes,
    add_makeup_class,
    remove_makeup_class,
)
from src import storage
from src.schedule_cache import (
    load_feed_cache,
    save_feed_cache,
    load_cached_exams,
    save_cached_exams,
)

PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "public"))
WEB_DIR = PUBLIC_DIR
# Paths imported from src.app_config

app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")

# Clean up legacy single-user cache on boot so no user data is retained across global restarts
legacy_token_path = os.path.join(PROJECT_ROOT, "data", ".token_cache.json")
if os.path.exists(legacy_token_path):
    try:
        os.remove(legacy_token_path)
    except Exception:
        pass


MSSV_REGEX = re.compile(r"^[0-9A-Za-z]{5,15}$")


def validate_mssv(mssv: Optional[str]) -> bool:
    """Validate that MSSV contains strictly 5 to 15 alphanumeric characters."""
    if not mssv or not isinstance(mssv, str):
        return False
    return bool(MSSV_REGEX.fullmatch(mssv.strip()))


def extract_jwt_identity(token: str) -> Optional[dict]:
    """Extract verified identity claims from JWT token if structure is valid."""
    if not token or not isinstance(token, str):
        return None
    try:
        parts = token.strip().split(".")
        if len(parts) == 3:
            payload = parts[1]
            payload += "=" * ((4 - len(payload) % 4) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
            mssv = (
                data.get("nameid")
                or data.get("unique_name")
                or data.get("sub")
                or data.get("Id")
                or data.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier")
            )
            fullname = (
                data.get("FullName")
                or data.get("name")
                or data.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name")
                or mssv
            )
            expire = data.get("exp")
            if mssv and validate_mssv(str(mssv)):
                return {
                    "Id": str(mssv).strip(),
                    "FullName": str(fullname).strip() if fullname else str(mssv).strip(),
                    "Expire": expire,
                }
    except Exception:
        pass
    return None


@app.errorhandler(SessionExpired)
def handle_session_expired(e):
    """Handle expired student portal sessions across all routes."""
    return jsonify({
        "success": False,
        "reason": "expired",
        "message": "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại."
    }), 401


@app.errorhandler(405)
def handle_method_not_allowed(e):
    """Ensure non-existent API routes return 404 rather than 405 from static catch-all."""
    if request.path.startswith("/api/"):
        rules = [r for r in app.url_map.iter_rules() if r.rule == request.path]
        if not rules:
            return jsonify({"success": False, "error": "Not Found"}), 404
    return jsonify({"success": False, "error": "Method Not Allowed"}), 405


def get_session_secret() -> Optional[str]:
    """Retrieve session secret strictly from SESSION_SECRET environment variable."""
    secret = os.environ.get("SESSION_SECRET")
    if not secret or not secret.strip():
        return None
    return secret.strip()


def get_client_ip() -> str:
    """Extract client IP handling proxies / Vercel headers."""
    if os.environ.get("VERCEL"):
        ip = request.headers.get("x-vercel-forwarded-for") or request.headers.get("x-real-ip")
        if ip:
            return ip.split(",")[0].strip()
    return (request.remote_addr or "127.0.0.1").strip()


def check_rate_limit(key: str, limit: int, window_sec: int) -> bool:
    """
    Returns True if request is allowed, False if rate limit exceeded.
    Uses atomic storage.incr_with_ttl.
    """
    count = storage.incr_with_ttl(key, window_sec)
    return count <= limit


def set_session_cookie(response, session_id: Optional[str], max_age: Optional[int] = None) -> bool:
    """
    Set hardened HTTP session cookie.
    Cookie holds ONLY the random session ID (zero portal_token or user data in cookies).
    Refuses if session_id is None or if SESSION_SECRET is missing.
    """
    if not session_id:
        return False
    if not get_session_secret():
        print("[Security Error] SESSION_SECRET is missing. Refusing to issue session cookie.")
        return False

    is_https = bool(os.environ.get("VERCEL") or request.is_secure or (request.headers.get("X-Forwarded-Proto", "").lower() == "https"))
    cookie_max_age = max_age if max_age is not None else 86400
    response.set_cookie(
        "hcmute_session",
        str(session_id).strip(),
        max_age=cookie_max_age,
        httponly=True,
        secure=is_https,
        samesite="Lax",
        path="/"
    )
    return True


def _calculate_token_ttl(expire_val: Any) -> int:
    """
    Calculate TTL in seconds for portal session.
    Clamped strictly between 5 minutes (300s) and 24 hours (86400s).
    """
    default_ttl = 7200
    ttl = default_ttl
    if expire_val:
        try:
            num = float(expire_val)
            if num > 1000000000:  # Epoch timestamp
                diff = int(num - time.time())
                ttl = diff if diff > 0 else default_ttl
            elif num > 0:  # Duration in seconds
                ttl = int(num)
        except (ValueError, TypeError):
            if isinstance(expire_val, str):
                try:
                    dt = datetime.fromisoformat(expire_val.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    diff = int((dt - datetime.now(timezone.utc)).total_seconds())
                    if diff > 0:
                        ttl = diff
                except Exception:
                    pass

    return max(300, min(86400, ttl))


def get_request_session() -> Optional[dict]:
    """
    Extract session from cookie 'hcmute_session', header 'X-Session-Token',
    or 'Authorization: Bearer <token>'.
    Queries persistent storage key session:<token>.
    Query parameters (?session_token=, ?token=) are strictly rejected.
    """
    token = request.cookies.get("hcmute_session", "").strip()
    if not token:
        token = request.headers.get("X-Session-Token", "").strip()
    if not token:
        auth = request.headers.get("Authorization", "").strip()
        if auth.startswith("Bearer "):
            token = auth[7:].strip()

    if not token:
        return None

    # Handle legacy base64 if still presenting old format
    if "." in token:
        try:
            raw = base64.urlsafe_b64decode(token.split(".")[0] + "==").decode("utf-8")
            unpacked = json.loads(raw)
            if isinstance(unpacked, dict) and unpacked.get("session_token"):
                token = unpacked["session_token"]
        except Exception:
            pass

    session = storage.get_json(f"session:{token}")
    if session and isinstance(session, dict):
        return session

    return None


def get_session_client(session: Optional[dict] = None) -> Optional[HCMUTEClient]:
    """Create an ephemeral HCMUTEClient strictly bound to the requesting user's session token."""
    if session is None:
        session = get_request_session()
    if not session:
        return None

    portal_token = session.get("portal_token")
    if not portal_token:
        return None

    session_data = session.get("session_data") or {
        "Id": session.get("mssv"),
        "FullName": session.get("name"),
        "Role": session.get("role", "SV"),
        "StudyStatusName": session.get("status", "Đang học"),
        "Token": portal_token,
    }
    return make_portal_client(token=portal_token, session_data=session_data)


# Background tasks removed - zero background polling loops


@app.before_request
def _start_request_timer():
    request._start_time = time.time()


@app.after_request
def add_cache_headers(response):
    """Enforce strict no-cache headers, security headers (CSP), and add X-Response-Time."""
    start_time = getattr(request, "_start_time", None)
    if start_time is not None:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        response.headers["X-Response-Time"] = f"{duration_ms}ms"
        if not os.environ.get("VERCEL") or response.status_code >= 500:
            log_entry = {
                "type": "request",
                "method": request.method,
                "route": request.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            }
            print(json.dumps(log_entry, ensure_ascii=False))

    # Security Headers (Prompt 9)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; style-src-attr 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "object-src 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"

    if request.path.startswith("/calendar/") or request.path == "/api/public-config":
        pass
    elif request.path.startswith("/api/") or request.path in ["/", "/bao-mat", "/dieu-khoan", "/security", "/terms"]:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    else:
        # Cache static assets (CSS, JS, fonts, images) for 24 hours
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    return response


@app.route("/api/public-config", methods=["GET"])
def api_public_config():
    """
    Public configuration endpoint exposing non-sensitive URLs & contact information.
    Strictly rate limited to 30 requests/minute/IP.
    """
    client_ip = request.remote_addr or "unknown"
    if not check_rate_limit(f"rl:pubcfg:{client_ip}", limit=30, window_sec=60):
        return jsonify({"success": False, "message": "Quá nhiều yêu cầu. Vui lòng thử lại sau."}), 429

    contact_email = os.environ.get("CONTACT_EMAIL", "").strip()
    repo_url = os.environ.get("GITHUB_REPO_URL", "").strip()
    template_url = os.environ.get("AUTO_SYNC_TEMPLATE_URL", "").strip()

    resp = jsonify({
        "version": APP_VERSION,
        "contact_email": contact_email,
        "repo_url": repo_url,
        "auto_sync_template_url": template_url,
    })
    resp.headers["Cache-Control"] = "public, max-age=300, s-maxage=300"
    return resp


@app.route("/health", methods=["GET", "HEAD"])
def health_check():
    """
    Lightweight health check endpoint returning service status and Upstash Redis connectivity.
    """
    return jsonify({
        "status": "ok",
        "redis": bool(storage.ping()),
    })


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html", max_age=0)


@app.route("/hoi-dap")
@app.route("/faq")
def faq_page():
    return send_from_directory(WEB_DIR, "faq.html", max_age=0)


@app.route("/dan-lich")
def paste_page():
    return send_from_directory(WEB_DIR, "dan-lich.html", max_age=0)


@app.route("/bao-mat")
@app.route("/security")
def security_page():
    return send_from_directory(WEB_DIR, "security.html", max_age=0)


@app.route("/dieu-khoan")
@app.route("/terms")
def terms_page():
    return send_from_directory(WEB_DIR, "terms.html", max_age=0)


@app.route("/api/status", methods=["GET"])
def api_status():
    """
    Return login state and student profile for the requesting client.
    Enforces per-browser session isolation via session token.
    Unauthenticated requests always receive authenticated: false.
    """
    session = get_request_session()
    if not session or not session.get("portal_token"):
        token = request.headers.get("X-Session-Token", "").strip() or request.cookies.get("hcmute_session", "").strip()
        reason = "expired" if token else "no_session"
        return jsonify({"authenticated": False, "reason": reason})

    s_id = str(session.get("mssv", "")).strip()
    s_name = session.get("name", "Sinh viên")
    return jsonify({
        "authenticated": True,
        "session_token": session.get("session_token"),
        "profile": {
            "id": s_id,
            "name": s_name,
            "role": session.get("role", "SV"),
            "status": session.get("status", "Đang học"),
            "expire": session.get("expire"),
        }
    })


def _get_login_rate_limit_keys(client_ip: str, mssv: Optional[str]) -> tuple[str, Optional[str]]:
    ip_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
    ip_key = f"rl:login:ip:{ip_hash}"
    mssv_key = f"rl:login:mssv:{mssv.strip()}" if mssv and validate_mssv(mssv) else None
    return ip_key, mssv_key


LOGIN_FREE_ATTEMPTS = 2        # the 3rd wrong password starts the lock
LOGIN_FIRST_LOCK_SEC = 15
LOGIN_MAX_LOCK_SEC = 300       # never lock for more than 5 minutes
LOGIN_FAIL_WINDOW_SEC = 1800   # failures are forgotten after 30 minutes
# Many students share the campus Wi-Fi address, so the per-IP limit is only a coarse backstop.
LOGIN_IP_MAX_FAILURES = 30


def _login_lock_seconds(failures: int) -> int:
    """Wrong password #3 -> 15s, then 30s, 60s, 120s, 240s, capped at 5 minutes."""
    if failures <= LOGIN_FREE_ATTEMPTS:
        return 0
    return min(LOGIN_MAX_LOCK_SEC, LOGIN_FIRST_LOCK_SEC * 2 ** (failures - LOGIN_FREE_ATTEMPTS - 1))


def _login_lock_key(mssv_key: str) -> str:
    return mssv_key.replace("rl:login:mssv:", "rl:login:lock:", 1)


def _login_retry_after(ip_key: str, mssv_key: Optional[str]) -> int:
    """Seconds the caller must still wait before another login attempt (0 = allowed)."""
    try:
        if int(storage.get_json(ip_key, default=0) or 0) >= LOGIN_IP_MAX_FAILURES:
            return LOGIN_MAX_LOCK_SEC
    except (ValueError, TypeError):
        pass
    if mssv_key:
        until = storage.get_json(_login_lock_key(mssv_key), default=0)
        try:
            return max(0, int(float(until or 0) - time.time() + 0.999))
        except (ValueError, TypeError):
            pass
    return 0


def _record_failed_login(ip_key: str, mssv_key: Optional[str]) -> int:
    """Count a failure and return the lock (seconds) it triggered, 0 if none yet."""
    storage.incr_with_ttl(ip_key, ttl=600)
    if not mssv_key:
        return 0
    failures = storage.incr_with_ttl(mssv_key, ttl=LOGIN_FAIL_WINDOW_SEC)
    seconds = _login_lock_seconds(failures)
    if seconds:
        storage.set_json(_login_lock_key(mssv_key), time.time() + seconds, ttl=seconds + 5)
    return seconds


def _login_lock_message(seconds: int) -> str:
    wait = f"{seconds} giây" if seconds < 60 else f"{-(-seconds // 60)} phút"
    return f"Quá tam ba bận nha bạn! Nghỉ tay chút rồi thử lại sau {wait}."


def _login_failure_response(message: str, ip_key: str, mssv_key: Optional[str], status: int = 400):
    seconds = _record_failed_login(ip_key, mssv_key)
    body = {"success": False, "message": message}
    if seconds:
        body["message"] = f"{message} {_login_lock_message(seconds)}"
        body["retry_after"] = seconds
    return jsonify(body), status


@app.route("/api/login", methods=["POST"])
def api_login():
    """
    Handle student login.
    Zero-Knowledge Multi-User Architecture:
    - Passwords are held in RAM only for the duration of the HTTPS request, then destroyed immediately.
    - An isolated session_token is generated and returned to the browser.
    - Passwords are NEVER written to disk, database, or server logs.
    - Token lifetime is strictly reported via 'expire'.
    """
    client_ip = get_client_ip()
    data = request.json or {}
    token_input = data.get("token", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    ip_key, mssv_key = _get_login_rate_limit_keys(client_ip, username)
    retry_after = _login_retry_after(ip_key, mssv_key)
    if retry_after:
        resp = jsonify({"success": False, "message": _login_lock_message(retry_after), "retry_after": retry_after})
        resp.headers["Retry-After"] = str(retry_after)
        return resp, 429

    client = make_portal_client()

    # Option 1: Direct Token Login (Zero Password)
    # Identity must come from verified portal token / JWT payload, NEVER from client-supplied username
    if token_input:
        jwt_info = extract_jwt_identity(token_input)
        if not jwt_info:
            return _login_failure_response(
                "Không thể xác thực danh tính sinh viên từ mã token này. Vui lòng đăng nhập bằng MSSV và Mật khẩu.",
                ip_key, mssv_key)

        client.token = token_input
        try:
            yt = client.get_year_and_term()
        except Exception as e:
            return _login_failure_response(f"Token không hợp lệ hoặc đã hết hạn: {e}", ip_key, mssv_key)

        mssv = jwt_info["Id"]
        name = jwt_info["FullName"]
        expire = jwt_info.get("Expire")

        session_payload = {
            "Id": mssv,
            "FullName": name,
            "Token": token_input,
            "Role": "SV",
            "StudyStatusName": "Đang học (Token Auth)",
            "Expire": expire,
        }
        client.session_data = session_payload

        session_token = secrets.token_urlsafe(32)
        session_rec = {
            "session_token": session_token,
            "mssv": mssv,
            "name": name,
            "role": session_payload["Role"],
            "status": session_payload["StudyStatusName"],
            "portal_token": token_input,
            "expire": expire,
            "session_data": session_payload,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_active": datetime.now(timezone.utc).isoformat(),
        }

        # Persistent storage: session:<token> with portal token TTL (clamped 5m - 24h)
        ttl_sec = _calculate_token_ttl(expire)
        storage.set_json(f"session:{session_token}", session_rec, ttl=ttl_sec)
        storage.sadd(f"user_sessions:{mssv}", session_token)

        # Pre-build calendar feed for instant webcal access
        try:
            feed_tok = get_or_create_feed_token(mssv)
            build_student_calendar_feed(mssv, feed_tok)
            touch_student_data_ttl(mssv)
        except Exception:
            pass

        # Anonymous daily active user stat (Prompt 5)
        today_vn_str = get_vietnam_now().strftime("%Y-%m-%d")
        touch_student_data_ttl(mssv)
        storage.incr_with_ttl(f"stats:dau:{today_vn_str}", 40 * 86400)

        resp = jsonify({
            "success": True,
            "session_token": session_token,
            "expire": expire,
            "profile": {
                "id": mssv,
                "name": name,
                "role": session_payload["Role"],
                "status": session_payload["StudyStatusName"],
                "expire": expire,
            }
        })
        set_session_cookie(resp, session_token, max_age=ttl_sec)
        return resp

    # Option 2: Standard MSSV + Password (Ephemeral, never stored)
    if not username or not password:
        return _login_failure_response("Vui lòng nhập MSSV và Mật khẩu.", ip_key, mssv_key)

    if not validate_mssv(username):
        return _login_failure_response(
            "Mã số sinh viên không hợp lệ (yêu cầu từ 5 đến 15 ký tự chữ và số).", ip_key, mssv_key)

    try:
        profile = client.login(username, password)
        # Explicit memory purge
        del password
        del data

        if mssv_key:
            storage.delete(mssv_key)
            storage.delete(_login_lock_key(mssv_key))
        session_token = secrets.token_urlsafe(32)
        mssv = str(profile.get("Id") or username).strip()
        if not validate_mssv(mssv):
            return jsonify({"success": False, "message": "Thông tin sinh viên từ cổng trường không hợp lệ."}), 400

        name = profile.get("FullName") or profile.get("Username", "Sinh viên")
        role = profile.get("Role", "SV")
        status = profile.get("StudyStatusName", "Đang học")
        expire = profile.get("Expire")

        session_rec = {
            "session_token": session_token,
            "mssv": mssv,
            "name": name,
            "role": role,
            "status": status,
            "portal_token": client.token,
            "expire": expire,
            "session_data": profile,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_active": datetime.now(timezone.utc).isoformat(),
        }

        # Persistent storage: session:<token> with portal token TTL (clamped 5m - 24h)
        ttl_sec = _calculate_token_ttl(expire)
        storage.set_json(f"session:{session_token}", session_rec, ttl=ttl_sec)
        storage.sadd(f"user_sessions:{mssv}", session_token)

        # Anonymous daily active user stat (Prompt 5)
        today_vn_str = get_vietnam_now().strftime("%Y-%m-%d")
        touch_student_data_ttl(mssv)
        storage.incr_with_ttl(f"stats:dau:{today_vn_str}", 40 * 86400)

        resp = jsonify({
            "success": True,
            "session_token": session_token,
            "expire": expire,
            "profile": {
                "id": mssv,
                "name": name,
                "role": role,
                "status": status,
                "expire": expire,
            }
        })
        set_session_cookie(resp, session_token, max_age=ttl_sec)
        return resp
    except Exception as e:
        try:
            del password
            del data
        except Exception:
            pass
        return _login_failure_response(str(e), ip_key, mssv_key)



def touch_student_data_ttl(mssv: str) -> None:
    """Refresh 150-day TTL for all cached student data."""
    clean_mssv = str(mssv).strip()
    if not validate_mssv(clean_mssv):
        return
    storage.expire(f"feed_cache:{clean_mssv}", DATA_TTL_SECONDS)
    storage.expire(f"exam_cache:{clean_mssv}", DATA_TTL_SECONDS)
    storage.expire(f"makeup:{clean_mssv}", DATA_TTL_SECONDS)
    storage.expire(f"cancelled:{clean_mssv}", DATA_TTL_SECONDS)
    storage.expire(f"schedule_snapshot:{clean_mssv}", DATA_TTL_SECONDS)
    feed_tok = storage.get_json(f"feedtok_by:{clean_mssv}")
    if feed_tok and isinstance(feed_tok, str):
        storage.expire(f"feedtok_by:{clean_mssv}", DATA_TTL_SECONDS)
        storage.expire(f"feedtok:{feed_tok}", DATA_TTL_SECONDS)
        storage.expire(f"feed:{feed_tok}", DATA_TTL_SECONDS)


def delete_all_student_records(mssv: str) -> None:
    """
    Completely purge all server-side records for a specific student:
    1. Active sessions in storage (session:<id>) and user_sessions:<mssv>
    2. Feed tokens feedtok:<token> and feedtok_by:<mssv>
    3. Caches (feed_cache:<mssv>, exam_cache:<mssv>, schedule_snapshot:<mssv>, makeup:<mssv>, cancelled:<mssv>)
    4. Local disk data/users/<mssv> if present
    """
    clean_mssv = str(mssv).strip()
    if not validate_mssv(clean_mssv):
        return

    # 1. Active sessions
    session_tokens = storage.smembers(f"user_sessions:{clean_mssv}")
    for sid in session_tokens:
        storage.delete(f"session:{sid}")
    storage.delete(f"user_sessions:{clean_mssv}")

    # 2. Feed tokens
    old_tok = storage.get_json(f"feedtok_by:{clean_mssv}")
    if old_tok:
        storage.delete(f"feedtok:{old_tok}")
        storage.delete(f"feed:{old_tok}")
    storage.delete(f"feedtok_by:{clean_mssv}")
    storage.delete(f"rl:refresh:{clean_mssv}")

    # 3. User personal schedule data
    storage.delete(f"makeup:{clean_mssv}")
    storage.delete(f"cancelled:{clean_mssv}")
    storage.delete(f"feed_cache:{clean_mssv}")
    storage.delete(f"exam_cache:{clean_mssv}")
    storage.delete(f"schedule_snapshot:{clean_mssv}")

    # 6. Local directory if present
    base_users_dir = os.path.abspath(os.path.join(BASE_DATA_DIR, "users"))
    target_dir = os.path.abspath(os.path.join(base_users_dir, clean_mssv))
    if target_dir.startswith(base_users_dir + os.sep) and os.path.exists(target_dir):
        try:
            import shutil
            shutil.rmtree(target_dir)
        except Exception:
            pass


@app.route("/api/logout", methods=["POST"])
def api_logout():
    """Handle student logout by completely purging server-side records and revoking browser session."""
    session = get_request_session()
    if session:
        mssv = session.get("mssv")
        if mssv and validate_mssv(str(mssv)):
            delete_all_student_records(str(mssv).strip())

    resp = jsonify({"success": True})
    resp.delete_cookie("hcmute_session")
    return resp


@app.route("/api/security/audit", methods=["GET"])
def api_security_audit():
    """
    Public Security & Privacy Transparency Audit endpoint.
    Accurately reports real persistence state of authentication caches, storage, and data policies.
    """
    is_upstash = bool(os.environ.get("UPSTASH_REDIS_REST_URL") and os.environ.get("UPSTASH_REDIS_REST_TOKEN"))
    storage_type = "Upstash Redis REST (Cloud Serverless)" if is_upstash else "Local File Storage (Local Mode)"
    template_configured = bool(os.environ.get("AUTO_SYNC_TEMPLATE_URL", "").strip())

    return jsonify({
        "success": True,
        "audit": {
            "disclaimer": APP_DISCLAIMER,
            "password_persistence": "KHÔNG lưu mật khẩu trên máy chủ. Mật khẩu được dùng một lần để đăng nhập cổng trường rồi giải phóng khỏi bộ nhớ ngay.",
            "storage_backend": storage_type,
            "modes": {
                "default_mode": {
                    "name": "Chế độ mặc định (đường dẫn Lịch)",
                    "password_handling": "Máy chủ KHÔNG lưu mật khẩu. Khi sinh viên mở trang, mật khẩu được dùng một lần để đăng nhập cổng trường rồi bỏ ngay khỏi RAM.",
                    "stored_items": [
                        {
                            "data": "Nội dung lịch đã dựng (Lịch học & Lịch thi)",
                            "purpose": "Để ứng dụng Lịch (Apple Calendar, Google Calendar) tải về",
                            "storage": "Khóa feed:<token>",
                            "ttl": "Tối đa 150 ngày (một học kỳ)",
                            "deletion": "Bấm nút 'Xoá dữ liệu của tôi' hoặc khi đăng xuất"
                        },
                        {
                            "data": "Liên kết Lịch ngẫu nhiên",
                            "purpose": "Chuỗi khóa ngẫu nhiên thay thế MSSV trong đường dẫn Lịch",
                            "storage": "Khóa feedtok:<token> và feedtok_by:<mssv>",
                            "ttl": "Tối đa 150 ngày (một học kỳ)",
                            "deletion": "Bấm nút 'Tạo lại liên kết' hoặc 'Xoá dữ liệu của tôi'"
                        },
                        {
                            "data": "Phiên đăng nhập tạm",
                            "purpose": "Giữ trạng thái đăng nhập trên trình duyệt",
                            "storage": "Cookie HttpOnly session:<token>",
                            "ttl": "Thời hạn phiên cổng trường (khoảng vài giờ, tối đa 24 giờ)",
                            "deletion": "Bấm nút 'Đăng xuất' hoặc 'Xoá dữ liệu của tôi'"
                        }
                    ]
                },
                "spreadsheet_auto_sync_mode": {
                    "name": "Chế độ tự cập nhật (bảng tính Google Sheets)",
                    "available": template_configured,
                    "password_handling": "Mật khẩu nằm trong tài khoản Google của chính sinh viên (PropertiesService.getUserProperties), không gửi đến máy chủ của dự án."
                }
            },
            "not_stored": [
                "Mật khẩu sinh viên",
                "Lịch sử truy cập kèm MSSV",
                "Địa chỉ IP thô của sinh viên",
                "Điểm số, bảng điểm",
                "Số CCCD / CMND",
                "Tài khoản ngân hàng, thông tin tài chính"
            ],
            "data_deletion": {
                "immediate": "Nút 'Xoá dữ liệu của tôi' trên giao diện web (POST /api/security/wipe-my-data)",
                "manual_request": "Xem mục Liên hệ trên trang /bao-mat (xử lý trong vòng 72 giờ nếu gửi email)"
            }
        }
    })


@app.route("/api/security/wipe-my-data", methods=["POST"])
def api_security_wipe():
    """1-Click Data Wipe (Right to be Forgotten). Clears session and all server records for requesting student."""
    session = get_request_session()
    if not session:
        return jsonify({"success": False, "message": "Chưa đăng nhập."}), 401

    mssv = session.get("mssv")
    if not mssv or not validate_mssv(str(mssv)):
        return jsonify({"success": False, "message": "Mã số sinh viên không hợp lệ."}), 400

    mssv = str(mssv).strip()
    delete_all_student_records(mssv)

    resp = jsonify({"success": True, "message": "Đã xóa toàn bộ phiên đăng nhập và dữ liệu cục bộ của bạn thành công."})
    resp.delete_cookie("hcmute_session")
    return resp


@app.route("/api/overview", methods=["GET"])
def api_overview():
    """Fetch current year & term, class schedule, and exam schedule with persistent cache fallback."""
    session = get_request_session()
    if not session:
        return jsonify({"success": False, "message": "Chưa đăng nhập."}), 401

    client = get_session_client(session)
    if not client or not client.ensure_authenticated():
        return jsonify({"success": False, "message": "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại."}), 401

    mssv = str(session.get("mssv", "")).strip()
    now = get_vietnam_now()

    include_past = request.args.get("include_past", "false").lower() == "true"
    include_past_exams = request.args.get("include_past_exams", "false").lower() == "true"
    req_year = request.args.get("year", "").strip()
    req_term = request.args.get("term", "").strip()
    force_refresh = request.args.get("force", "0") in ("1", "true", "True")
    if force_refresh and not check_rate_limit(f"rl:force:{mssv}", limit=6, window_sec=60):
        force_refresh = False

    # Serve cached overview immediately when fresh (<10 min) instead of calling portal
    if not force_refresh and not req_year and not req_term:
        cached_overview = storage.get_json(f"overview_cache:{mssv}")
        if cached_overview and isinstance(cached_overview, dict):
            ts = cached_overview.get("timestamp", 0)
            if (time.time() - ts) < 600:
                cached_data = cached_overview.get("data")
                if cached_data and isinstance(cached_data, dict):
                    cancelled_set = load_cancellations(mssv)
                    for c in cached_data.get("classes", []):
                        c["is_cancelled"] = c.get("uid") in cancelled_set
                    return jsonify(cached_data)

    all_class_events = []
    all_raw_exams = []
    def_year, def_term = guess_current_term()
    curr_year = def_year
    curr_term = def_term
    available_years = get_available_years()
    available_terms = [
        {"TermID": "HK01", "TermName": "Học kỳ 1"},
        {"TermID": "HK02", "TermName": "Học kỳ 2"},
        {"TermID": "HK03", "TermName": "Học kỳ 3"}
    ]

    try:
        try:
            from concurrent.futures import ThreadPoolExecutor, wait
            pool = ThreadPoolExecutor(max_workers=4)
            try:
                cached_yt = storage.get_json(f"terms_cache:{mssv}")

                # Check 1-hour fast storage cache for academic years & terms
                if cached_yt and isinstance(cached_yt, dict):
                    yt = cached_yt
                    available_years = yt.get("YearStudy") or available_years
                    available_terms = yt.get("Terms") or available_terms
                    curr_year = req_year or yt.get("CurrentYear") or yt.get("NamHienTai") or curr_year
                    curr_term = req_term or yt.get("CurrentTerm") or yt.get("HocKyHienTai") or curr_term
                    fut_yt = None
                else:
                    fut_yt = pool.submit(client.get_year_and_term)

                curr_year = req_year or curr_year
                curr_term = req_term or curr_term

                # Submit all queries concurrently in parallel (Zero Sequential Stalling)
                fut_sched = pool.submit(client.get_schedule_semester, curr_year, curr_term)
                fut_time_exams = pool.submit(client.get_exams_by_time)
                fut_term_exams = pool.submit(client.get_exam_schedule, curr_year, curr_term)

                all_futs = [f for f in [fut_yt, fut_sched, fut_time_exams, fut_term_exams] if f is not None]
                # Fast bounded parallel timeout: never hang or freeze the browser
                done, _ = wait(all_futs, timeout=3.2)

                if fut_yt and fut_yt in done:
                    try:
                        yt = fut_yt.result()
                        available_years = yt.get("YearStudy") or available_years
                        available_terms = yt.get("Terms") or available_terms
                        storage.set_json(f"terms_cache:{mssv}", yt, ttl=3600)
                    except Exception:
                        pass

                if fut_sched in done:
                    try:
                        raw_sched = fut_sched.result()
                        classes_res, _ = parse_semester_schedule(raw_sched)
                        if classes_res:
                            all_class_events = classes_res
                            save_feed_cache(all_class_events, mssv=mssv)
                    except Exception:
                        pass

                if fut_time_exams in done:
                    try:
                        all_raw_exams.extend(fut_time_exams.result())
                    except Exception:
                        pass

                if fut_term_exams in done:
                    try:
                        all_raw_exams.extend(fut_term_exams.result())
                    except Exception:
                        pass
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

        # Fallback to cached classes if live fetch failed
        if not all_class_events:
            cached_events = load_feed_cache(mssv=mssv)
            all_class_events = [c for c in cached_events if (c.event_type or "").upper() in ("CLASS", "TKB")]

        # Always include make-up classes for this student!
        all_class_events.extend(load_makeup_classes(mssv))
        from src.schedule_parser import assign_course_colors
        assign_course_colors(all_class_events)

        # Parse live exams
        try:
            exam_events, _ = parse_exam_schedule(all_raw_exams)
        except Exception:
            exam_events = []

        # Fallback to cached exams if live exams returned empty
        if not exam_events:
            exam_events = load_cached_exams(mssv=mssv)
        else:
            save_cached_exams(exam_events, mssv=mssv)

        assign_course_colors(exam_events)

        # Deduplicate exams by title and date
        deduped_exams = []
        seen_exam_keys = set()
        for ex in exam_events:
            k = (ex.title, ex.start_datetime.strftime("%Y%m%d%H%M"))
            if k not in seen_exam_keys:
                seen_exam_keys.add(k)
                deduped_exams.append(ex)

        upcoming_classes = [c for c in all_class_events if c.end_datetime >= now]
        upcoming_classes.sort(key=lambda x: x.start_datetime)

        past_classes = [c for c in all_class_events if c.end_datetime < now]
        past_classes.sort(key=lambda x: x.start_datetime, reverse=True)

        # Keep exams from past 7 days in upcoming_exams so active exam week is never empty
        upcoming_exams = [e for e in deduped_exams if e.start_datetime >= now - timedelta(days=7)]
        upcoming_exams.sort(key=lambda x: x.start_datetime)

        past_exams = [e for e in deduped_exams if e.start_datetime < now - timedelta(days=7)]
        past_exams.sort(key=lambda x: x.start_datetime, reverse=True)

        classes_to_return = all_class_events if include_past else upcoming_classes
        classes_to_return.sort(key=lambda x: x.start_datetime)

        cancelled_set = load_cancellations(mssv)
        classes_data = []
        for c in classes_to_return:
            d = c.to_dict()
            d["is_cancelled"] = c.uid in cancelled_set
            classes_data.append(d)

        exams_to_return = deduped_exams if include_past_exams else upcoming_exams
        exams_to_return.sort(key=lambda x: x.start_datetime)

        resp_payload = {
            "success": True,
            "year": curr_year,
            "term": curr_term,
            "years": available_years,
            "terms": available_terms,
            "include_past": include_past,
            "include_past_exams": include_past_exams,
            "total_classes_count": len(all_class_events),
            "upcoming_classes_count": len(upcoming_classes),
            "past_classes_count": len(past_classes),
            "class_count": len(classes_to_return),
            "total_exams_count": len(deduped_exams),
            "upcoming_exams_count": len(upcoming_exams),
            "past_exams_count": len(past_exams),
            "exam_count": len(exams_to_return),
            "classes": classes_data,
            "exams": [e.to_dict() for e in exams_to_return],
        }
        if not req_year and not req_term:
            storage.set_json(f"overview_cache:{mssv}", {"data": resp_payload, "timestamp": time.time()}, ttl=600)

        return jsonify(resp_payload)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/considerations", methods=["GET"])
def api_considerations():
    """Scan announcements, fee debt, and upcoming exams to formulate reminder recommendations."""
    session = get_request_session()
    if not session:
        return jsonify({"success": False, "message": "Chưa đăng nhập."}), 401

    client = get_session_client(session)
    if not client or not client.ensure_authenticated():
        return jsonify({"success": False, "message": "Chưa đăng nhập hoặc phiên đã hết hạn."}), 401

    mssv = str(session.get("mssv", "default")).strip()
    import time
    force = request.args.get("force", "0") in ("1", "true", "True")
    if force and not check_rate_limit(f"rl:force:{mssv}", limit=6, window_sec=60):
        force = False

    user_cached = storage.get_json(f"considerations:{mssv}")
    if not force and user_cached and isinstance(user_cached, dict):
        if (time.time() - user_cached.get("timestamp", 0) < 600):
            cached_data = user_cached.get("data", [])
            return jsonify({"success": True, "count": len(cached_data), "items": cached_data})

    try:
        from src.notice_analyzer import ConsiderationItem, decrypt_hcmute_body
        from concurrent.futures import ThreadPoolExecutor, wait

        analyzer = NoticeAnalyzer(load_config())
        now = get_vietnam_now()
        all_items: List[ConsiderationItem] = []

        # 1. Upcoming exams from cached exams or quick fetch
        try:
            cached_exams = load_cached_exams(mssv=mssv)
            if cached_exams:
                for ex in cached_exams:
                    exam_dt = ex.start_datetime
                    if exam_dt >= now - timedelta(hours=12):
                        days_left = (exam_dt.date() - now.date()).days
                        countdown_str = "HÔM NAY" if days_left == 0 else ("NGÀY MAI" if days_left == 1 else f"Còn {days_left} ngày")
                        exam_item = ConsiderationItem(
                            item_id=f"exam_{ex.uid}",
                            title=f"Lịch thi: {ex.title} ({countdown_str})",
                            category="EXAM",
                            priority="HIGH",
                            deadline=exam_dt,
                            summary=f"Thi môn {ex.title} lúc {exam_dt.strftime('%H:%M')} ngày {exam_dt.strftime('%d/%m/%Y')}.",
                            action_required=f"Có mặt trước giờ thi 15 phút tại Phòng {ex.location}. Mang theo thẻ SV/CCCD.",
                            recommendation="Kỳ thi kết thúc học phần bắt buộc có mặt đúng giờ.",
                            source_title=f"Lịch thi: {ex.title}",
                            source_id=f"exam_{ex.uid}",
                            source_date=now,
                            confidence_score=1.0,
                            is_reminder_needed=True,
                            notice_type="exam",
                            full_content=f"<h3>Lịch thi: {ex.title}</h3><p><b>Thời gian:</b> {exam_dt.strftime('%d/%m/%Y %H:%M')}</p><p><b>Phòng thi:</b> {ex.location}</p>",
                        )
                        all_items.append(exam_item)
            else:
                exams_raw = client.get_exams_by_time()
                for ex in exams_raw:
                    ngay_raw = ex.get("NgayThi")
                    gio_raw = ex.get("GioThi") or "07:30"
                    if not ngay_raw:
                        continue
                    import re
                    m_d = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", ngay_raw)
                    if not m_d:
                        continue
                    d, m, y = map(int, m_d.groups())
                    hh, mm = 7, 30
                    m_t = re.search(r"(\d{1,2})(?:g|h|:)(\d{2})", gio_raw)
                    if m_t:
                        hh, mm = int(m_t.group(1)), int(m_t.group(2))
                    exam_dt = datetime(y, m, d, hh, mm)

                    if exam_dt >= now - timedelta(hours=12):
                        subj_name = ex.get("CurriculumName") or ex.get("TenHP") or "Môn thi"
                        room = ex.get("PhongThi") or "Xem thông báo"
                        loc = ex.get("DiaDiem") or "Cơ sở chính"
                        days_left = (exam_dt.date() - now.date()).days
                        countdown_str = "HÔM NAY" if days_left == 0 else ("NGÀY MAI" if days_left == 1 else f"Còn {days_left} ngày")

                        exam_item = ConsiderationItem(
                            item_id=f"exam_{ex.get('CurriculumID')}_{exam_dt.strftime('%Y%m%d')}",
                            title=f"Lịch thi: {subj_name} ({countdown_str})",
                            category="EXAM",
                            priority="HIGH",
                            deadline=exam_dt,
                            summary=f"Thi môn {subj_name} lúc {exam_dt.strftime('%H:%M')} ngày {exam_dt.strftime('%d/%m/%Y')}.",
                            action_required=f"Có mặt trước giờ thi 15 phút tại Phòng {room} ({loc}). Mang theo thẻ SV/CCCD.",
                            recommendation="Kỳ thi kết thúc học phần bắt buộc có mặt đúng giờ.",
                            source_title=f"Lịch thi chính thức: {subj_name}",
                            source_id=f"exam_{ex.get('CurriculumID')}",
                            source_date=now,
                            confidence_score=1.0,
                            is_reminder_needed=True,
                            notice_type="exam",
                            full_content=f"<h3>Lịch thi: {subj_name}</h3><p><b>Ngày thi:</b> {exam_dt.strftime('%d/%m/%Y')}</p><p><b>Giờ thi:</b> {exam_dt.strftime('%H:%M')}</p><p><b>Phòng thi:</b> Phòng {room} ({loc})</p><p><b>Thời gian làm bài:</b> {ex.get('ThoiLuong', 90)} phút</p><p><b>Số báo danh:</b> {ex.get('SBD', 'Theo danh sách')}</p><p><b>Ghi chú:</b> {ex.get('Note', '')}</p>",
                        )
                        all_items.append(exam_item)
        except Exception:
            pass

        # 2. Concurrently fetch Personal Notices, General Notices & Fee Debt with strict timeouts
        def fetch_personal():
            try:
                personal_notices = client.get_personal_messages()
                if not isinstance(personal_notices, list):
                    return
                # Capture up to 30 authentic personal inbox messages
                for p in personal_notices[:30]:
                    try:
                        item = analyzer.analyze_announcement(p, notice_type="personal")
                        if item:
                            all_items.append(item)
                    except Exception:
                        pass
            except Exception:
                pass

        def fetch_general():
            try:
                general_notices = client.get_general_announcements()
                if not isinstance(general_notices, list):
                    return
                # Capture up to 30 university-wide announcements
                for g in general_notices[:30]:
                    try:
                        item = analyzer.analyze_announcement(g, notice_type="general")
                        if item:
                            all_items.append(item)
                    except Exception:
                        pass
            except Exception:
                pass

        def fetch_tuition():
            try:
                fee_item = analyzer.analyze_tuition_debt(client.get_fee_debt())
                if fee_item:
                    all_items.insert(0, fee_item)
            except Exception:
                pass

        executor = ThreadPoolExecutor(max_workers=3)
        try:
            f1 = executor.submit(fetch_personal)
            f2 = executor.submit(fetch_general)
            f3 = executor.submit(fetch_tuition)
            wait([f1, f2, f3], timeout=5.0)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        # SORTING STRATEGY:
        # Group 0: Urgent upcoming deadlines (nearest to today first: 0d, 1d, 3d...)
        # Group 1: Fresh announcements & personal messages without fixed deadline (newest creation date first)
        # Group 2: Past deadlines
        def sort_key(it):
            if it.deadline:
                if it.deadline >= now - timedelta(days=1):
                    return (0, it.deadline.timestamp())
                else:
                    return (2, -it.deadline.timestamp())
            else:
                ts = it.source_date.timestamp() if it.source_date else 0
                return (1, -ts)

        all_items.sort(key=sort_key)

        # Deduplicate items with similar titles and same deadline
        deduped_items = []
        seen_keys = set()
        for it in all_items:
            dl_str = it.deadline.strftime("%Y%m%d") if it.deadline else "no_dl"
            clean_words = "".join(filter(str.isalnum, (it.title or "").lower()))[:30]
            key = f"{it.notice_type}_{it.category}_{dl_str}_{clean_words}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped_items.append(it)

        data = []
        for it in deduped_items:
            days_left = None
            if it.deadline:
                days_left = (it.deadline.date() - now.date()).days

            data.append({
                "id": it.item_id,
                "title": it.title,
                "category": it.category,
                "priority": it.priority,
                "deadline": it.deadline.strftime("%d/%m/%Y %H:%M") if it.deadline else None,
                "deadline_iso": it.deadline.isoformat() if it.deadline else None,
                "days_left": days_left,
                "action": it.action_required,
                "recommendation": it.recommendation,
                "source_title": it.source_title,
                "source_date": it.source_date.strftime("%d/%m/%Y") if it.source_date else None,
                "sender": getattr(it, "sender", "") or "Phòng Đào tạo HCMUTE",
                "is_needed": it.is_reminder_needed,
                "notice_type": it.notice_type,
            })

        payload_entry = {
            "timestamp": time.time(),
            "data": data,
        }
        storage.set_json(f"considerations:{mssv}", payload_entry, ttl=600)
        return jsonify({"success": True, "count": len(data), "items": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/notice-detail", methods=["GET"])
def api_notice_detail():
    """Fetch and decrypt full announcement body for reader modal."""
    session = get_request_session()
    if not session:
        return jsonify({"success": False, "message": "Chưa đăng nhập."}), 401

    client = get_session_client(session)
    if not client or not client.ensure_authenticated():
        return jsonify({"success": False, "message": "Chưa đăng nhập hoặc phiên đã hết hạn."}), 401

    notice_id = request.args.get("id", "").strip()
    notice_type = request.args.get("type", "personal").strip()

    if not notice_id:
        return jsonify({"success": False, "message": "Thiếu ID thông báo."}), 400

    from src.notice_analyzer import decrypt_hcmute_body

    try:
        if notice_type == "personal":
            detail = client.get_message_detail(notice_id)
            decrypted_body = decrypt_hcmute_body(detail.get("MessageBody", ""))
            return jsonify({
                "success": True,
                "id": notice_id,
                "subject": detail.get("MessageSubject") or "Thông báo cá nhân",
                "sender": detail.get("SenderName") or "Phòng Công tác sinh viên",
                "date": detail.get("CreationDate") or "",
                "content_html": decrypted_body,
            })
        elif notice_type == "exam":
            # Return exam info
            exams = client.get_exams_by_time()
            for ex in exams:
                if str(ex.get("CurriculumID")) in notice_id:
                    return jsonify({
                        "success": True,
                        "id": notice_id,
                        "subject": f"Lịch thi: {ex.get('CurriculumName')}",
                        "sender": "Phòng Đào tạo HCMUTE",
                        "date": ex.get("NgayThi", ""),
                        "content_html": f"<h3>{ex.get('CurriculumName')}</h3><p><b>Mã học phần:</b> {ex.get('CurriculumID')}</p><p><b>Ngày thi:</b> {ex.get('NgayThi')}</p><p><b>Giờ thi:</b> {ex.get('GioThi')}</p><p><b>Phòng thi:</b> Phòng {ex.get('PhongThi')}</p><p><b>Địa điểm:</b> {ex.get('DiaDiem')}</p><p><b>Kỳ thi:</b> {ex.get('KyThi')}</p><p><b>Số báo danh:</b> {ex.get('SBD') or 'Theo danh sách'}</p><p><b>Ghi chú:</b> {ex.get('Note', '')}</p>",
                    })
            return jsonify({"success": False, "message": "Không tìm thấy thông tin lịch thi."}), 404
        else:
            # General notice
            general_list = client.get_general_announcements()
            for g in general_list:
                if str(g.get("MaTin")) == str(notice_id) or str(g.get("Id")) == str(notice_id):
                    return jsonify({
                        "success": True,
                        "id": notice_id,
                        "subject": g.get("TieuDe") or g.get("MessageSubject") or "Thông báo chung",
                        "sender": g.get("StaffName") or "Phòng Đào tạo",
                        "date": g.get("CreateDate") or "",
                        "content_html": g.get("NoiDung") or "<p>Không có nội dung chi tiết.</p>",
                    })
            return jsonify({"success": False, "message": "Không tìm thấy thông báo chung."}), 404
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/export-ics", methods=["POST"])
def api_export_ics():
    """Export schedule, exams, and selected reminders to .ics file with granular category options."""
    session = get_request_session()
    if not session:
        return jsonify({"success": False, "message": "Yêu cầu đăng nhập để tải lịch."}), 401

    client = get_session_client(session)
    mssv = str(session.get("mssv", "")).strip()

    try:
        now = get_vietnam_now()

        req_data = request.json or {}
        include_classes = bool(req_data.get("include_classes", True))
        include_exams = bool(req_data.get("include_exams", True))
        include_reminders = bool(req_data.get("include_reminders", True))
        only_upcoming = bool(req_data.get("only_upcoming", True))
        selected_reminder_ids = set(req_data.get("selected_reminder_ids", []))

        def_year, def_term = guess_current_term()
        curr_year = def_year
        curr_term = def_term
        if client and client.is_authenticated():
            try:
                yt = client.get_year_and_term()
                curr_year = yt.get("CurrentYear") or yt.get("NamHienTai") or curr_year
                curr_term = yt.get("CurrentTerm") or yt.get("HocKyHienTai") or curr_term
            except Exception:
                pass

        all_events = []

        # 1. Fetch Schedule (if requested)
        if include_classes:
            classes = []
            if client and client.ensure_authenticated():
                try:
                    raw_sched = client.get_schedule_semester(curr_year, curr_term)
                    classes, _ = parse_semester_schedule(raw_sched)
                except Exception:
                    pass
            if not classes:
                cached = load_feed_cache(mssv=mssv)
                classes = [c for c in cached if (c.event_type or "").upper() in ("CLASS", "TKB")]

            # Include make-up classes!
            classes.extend(load_makeup_classes(mssv))

            cancelled_set = load_cancellations(mssv)
            classes = [c for c in classes if c.uid not in cancelled_set]
            if only_upcoming:
                classes = [c for c in classes if c.end_datetime >= now]
            all_events.extend(classes)

        # 2. Fetch Exams (if requested)
        if include_exams:
            parsed_exams = []
            if client and client.is_authenticated():
                raw_exams = []
                try:
                    raw_exams.extend(client.get_exams_by_time())
                except Exception:
                    pass
                try:
                    raw_exams.extend(client.get_exam_schedule(curr_year, curr_term))
                except Exception:
                    pass
                try:
                    parsed_exams, _ = parse_exam_schedule(raw_exams)
                except Exception:
                    parsed_exams = []

            if not parsed_exams:
                parsed_exams = load_cached_exams(mssv=mssv)
            else:
                save_cached_exams(parsed_exams, mssv=mssv)

            seen_exam_keys = set()
            for ex in parsed_exams:
                k = (ex.title, ex.start_datetime.strftime("%Y%m%d%H%M"))
                if k not in seen_exam_keys:
                    seen_exam_keys.add(k)
                    # For exams: keep all semester exams if exporting exams only,
                    # or keep exams within the past 30 days and upcoming.
                    if not only_upcoming or not include_classes or ex.start_datetime >= now - timedelta(days=30):
                        all_events.append(ex)

        # 3. Add Reminders (if requested)
        if include_reminders:
            analyzer = NoticeAnalyzer(load_config())
            if client and client.ensure_authenticated():
                try:
                    personal_notices = client.get_personal_messages()[:15]
                    for p in personal_notices:
                        mid = p.get("MessageID") or p.get("Id")
                        if mid and "MessageBody" not in p:
                            try:
                                p_detail = client.get_message_detail(mid)
                                p["MessageBody"] = p_detail.get("MessageBody", "")
                            except Exception:
                                pass
                        item = analyzer.analyze_announcement(p, notice_type="personal")
                        if item and (not selected_reminder_ids or item.item_id in selected_reminder_ids):
                            ev = item.to_calendar_event()
                            if ev:
                                all_events.append(ev)

                    for g in client.get_general_announcements()[:20]:
                        item = analyzer.analyze_announcement(g, notice_type="general")
                        if item and (not selected_reminder_ids or item.item_id in selected_reminder_ids):
                            ev = item.to_calendar_event()
                            if ev:
                                all_events.append(ev)

                    fee_item = analyzer.analyze_tuition_debt(client.get_fee_debt())
                    if fee_item and (not selected_reminder_ids or fee_item.item_id in selected_reminder_ids):
                        ev = fee_item.to_calendar_event()
                        if ev:
                            all_events.append(ev)
                except Exception:
                    pass

        if not all_events:
            return jsonify({"success": False, "message": "Không có sự kiện nào phù hợp với bộ lọc bạn đã chọn."}), 400

        # Descriptive filename
        if include_classes and not include_exams and not include_reminders:
            download_name = "hcmute_tkb.ics"
            cal_title = f"{APP_NAME} - Lịch học"
        elif include_exams and not include_classes and not include_reminders:
            download_name = "hcmute_lich_thi.ics"
            cal_title = f"{APP_NAME} - Lịch học"
        elif include_reminders and not include_classes and not include_exams:
            download_name = "hcmute_nhac_nho.ics"
            cal_title = f"{APP_NAME} - Lịch học"
        else:
            download_name = f"{APP_NAME}.ics"
            cal_title = f"{APP_NAME} - Lịch học"

        ics_bytes = events_to_ics_bytes(all_events, calendar_name=cal_title)
        return Response(
            ics_bytes,
            mimetype="text/calendar",
            headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500





DEFAULT_FEED_OPTIONS = {
    "reminder_min": 20,
    "title_style": "name",
    "split": False,
    "deadlines": False,
}


def get_student_feed_options(mssv: str) -> dict:
    opts = storage.get_json(f"feedopt:{mssv}")
    if not isinstance(opts, dict):
        return dict(DEFAULT_FEED_OPTIONS)
    merged = dict(DEFAULT_FEED_OPTIONS)
    merged.update(opts)
    return merged


def save_student_feed_options(mssv: str, opts: dict):
    storage.set_json(f"feedopt:{mssv}", opts, ttl=DATA_TTL_SECONDS)


def get_student_calendars_list(feed_tok: str, options: dict, host_url: str) -> list:
    clean_host = host_url.rstrip("/")
    webcal_base = clean_host.replace("https://", "webcal://").replace("http://", "webcal://")
    is_split = bool(options.get("split", False))
    has_deadlines = bool(options.get("deadlines", False))

    if not is_split:
        return [
            {
                "id": "all",
                "name": "Lịch học và lịch thi",
                "color": "#0072BC",
                "url": f"/calendar/{feed_tok}/all.ics",
                "webcal_url": f"{webcal_base}/calendar/{feed_tok}/all.ics",
            }
        ]

    cals = [
        {
            "id": "tkb",
            "name": "Lịch học",
            "color": "#0072BC",
            "url": f"/calendar/{feed_tok}/tkb.ics",
            "webcal_url": f"{webcal_base}/calendar/{feed_tok}/tkb.ics",
        },
        {
            "id": "thi",
            "name": "Lịch thi",
            "color": "#ED1C24",
            "url": f"/calendar/{feed_tok}/thi.ics",
            "webcal_url": f"{webcal_base}/calendar/{feed_tok}/thi.ics",
        },
    ]
    if has_deadlines:
        cals.append({
            "id": "han-chot",
            "name": "Hạn chót & thông báo",
            "color": "#D8B26A",
            "url": f"/calendar/{feed_tok}/han-chot.ics",
            "webcal_url": f"{webcal_base}/calendar/{feed_tok}/han-chot.ics",
        })
    return cals


def get_student_deadlines(mssv: str, client: Optional[Any] = None) -> List[CalendarEvent]:
    cached = storage.get_json(f"deadlines:{mssv}")
    if isinstance(cached, list):
        return [CalendarEvent.from_dict(d) for d in cached]
    if not client or not client.is_authenticated():
        return []
    try:
        analyzer = NoticeAnalyzer()
        notices = client.get_general_announcements() + client.get_personal_messages()
        considered = analyzer.analyze_all_announcements(notices)
        events = []
        for item in considered:
            if item.deadline:
                d_date = item.deadline.date()
                ev = CalendarEvent(
                    uid=f"ute-calendar-dl-{item.item_id}",
                    title=f"Hạn chót: {item.title}",
                    start_datetime=datetime.combine(d_date, time(0, 0)),
                    end_datetime=datetime.combine(d_date + timedelta(days=1), time(0, 0)),
                    location="",
                    description=f"{item.summary}\n{item.action_required}\nUTE-Calendar",
                    event_type="DEADLINE",
                    category="DEADLINE",
                    is_all_day=True,
                    color_id="4",
                    color_hex="#D8B26A",
                )
                events.append(ev)
        storage.set_json(f"deadlines:{mssv}", [e.to_dict() for e in events], ttl=86400 * 7)
        return events
    except Exception:
        return []


def build_student_calendar_feed(mssv: str, feed_token: Optional[str] = None) -> Optional[dict]:
    """
    Pre-build full iCalendar feed variants (.ics) for student.
    Stored under storage keys:
    - feed:<token>:all
    - feed:<token>:tkb
    - feed:<token>:thi
    - feed:<token>:han-chot
    - feed:<token> (backward compatibility, points to 'all')
    TTL up to DATA_TTL_SECONDS (120 days).
    """
    clean_mssv = str(mssv).strip()
    if not validate_mssv(clean_mssv):
        return None

    if not feed_token:
        feed_token = get_or_create_feed_token(clean_mssv)
    if not feed_token:
        return None

    options = get_student_feed_options(clean_mssv)
    now = get_vietnam_now()

    def _naive(dt):
        return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt

    # 1. Classes: load cached classes + make-up classes, filter cancellations and past classes
    cached = load_feed_cache(mssv=clean_mssv)
    classes = [c for c in cached if (c.event_type or "").upper() in ("CLASS", "TKB")]
    classes.extend(load_makeup_classes(clean_mssv))
    cancelled_set = load_cancellations(clean_mssv)
    if cancelled_set:
        classes = [c for c in classes if c.uid not in cancelled_set]
    classes = [c for c in classes if _naive(c.end_datetime) >= now]

    # Apply title_style option if requested
    if options.get("title_style") == "code_name":
        for ev in classes:
            m_code = re.search(r"Mã lớp:\s*(\S+)", ev.description)
            if m_code:
                code_str = m_code.group(1).strip()
                if code_str and not ev.title.startswith(f"[{code_str}]"):
                    ev.title = f"[{code_str}] {ev.title}"

    # 2. Exams: load cached exams, keep past 30 days and upcoming
    exams = load_cached_exams(mssv=clean_mssv)
    exams = [ex for ex in exams if _naive(ex.start_datetime) >= now - timedelta(days=30)]

    # 3. Deadlines: if option enabled
    deadlines = []
    if options.get("deadlines"):
        deadlines = get_student_deadlines(clean_mssv)

    now_ts = int(time.time())

    # Build expiry event (3 days before TTL), added ONLY to all and tkb
    try:
        from flask import has_request_context
        h_url = request.host_url.rstrip("/") if has_request_context() else "https://ute-calendar.com"
    except Exception:
        h_url = "https://ute-calendar.com"
    exp_ev = make_expiry_event(datetime.fromtimestamp(now_ts), h_url)

    rem_min = int(options.get("reminder_min", 20))

    # Variant All
    all_events = classes + exams + deadlines + [exp_ev]
    all_bytes = events_to_ics_bytes(
        all_events,
        calendar_name=f"{APP_NAME} - Thời khóa biểu & Lịch thi",
        add_reminders=True,
        calendar_color="#0072BC",
        reminder_min=rem_min,
    )
    all_str = all_bytes.decode("utf-8", errors="replace")
    all_etag = f'"{hashlib.md5(all_bytes).hexdigest()}"'
    rec_all = {
        "mssv": clean_mssv,
        "feed_token": feed_token,
        "variant": "all",
        "ics": all_str,
        "etag": all_etag,
        "updated_at": now_ts,
    }
    storage.set_json(f"feed:{feed_token}:all", rec_all, ttl=DATA_TTL_SECONDS)
    storage.set_json(f"feed:{feed_token}", rec_all, ttl=DATA_TTL_SECONDS)

    # Variant TKB
    tkb_events = classes + [exp_ev]
    tkb_bytes = events_to_ics_bytes(
        tkb_events,
        calendar_name=f"{APP_NAME} - Lịch học",
        add_reminders=True,
        calendar_color="#0072BC",
        reminder_min=rem_min,
    )
    rec_tkb = {
        "mssv": clean_mssv,
        "feed_token": feed_token,
        "variant": "tkb",
        "ics": tkb_bytes.decode("utf-8", errors="replace"),
        "etag": f'"{hashlib.md5(tkb_bytes).hexdigest()}"',
        "updated_at": now_ts,
    }
    storage.set_json(f"feed:{feed_token}:tkb", rec_tkb, ttl=DATA_TTL_SECONDS)

    # Variant Thi
    thi_bytes = events_to_ics_bytes(
        exams,
        calendar_name=f"{APP_NAME} - Lịch thi",
        add_reminders=True,
        calendar_color="#ED1C24",
        reminder_min=rem_min,
    )
    rec_thi = {
        "mssv": clean_mssv,
        "feed_token": feed_token,
        "variant": "thi",
        "ics": thi_bytes.decode("utf-8", errors="replace"),
        "etag": f'"{hashlib.md5(thi_bytes).hexdigest()}"',
        "updated_at": now_ts,
    }
    storage.set_json(f"feed:{feed_token}:thi", rec_thi, ttl=DATA_TTL_SECONDS)

    # Variant Han-Chot
    hanchot_bytes = events_to_ics_bytes(
        deadlines,
        calendar_name=f"{APP_NAME} - Hạn chót",
        add_reminders=True,
        calendar_color="#D8B26A",
        reminder_min=0,
    )
    rec_hanchot = {
        "mssv": clean_mssv,
        "feed_token": feed_token,
        "variant": "han-chot",
        "ics": hanchot_bytes.decode("utf-8", errors="replace"),
        "etag": f'"{hashlib.md5(hanchot_bytes).hexdigest()}"',
        "updated_at": now_ts,
    }
    storage.set_json(f"feed:{feed_token}:han-chot", rec_hanchot, ttl=DATA_TTL_SECONDS)

    return rec_all


def get_or_create_feed_token(mssv: str) -> str:
    safe_mssv = str(mssv).strip()
    if not safe_mssv:
        return ""
    existing_token = storage.get_json(f"feedtok_by:{safe_mssv}")
    if existing_token and isinstance(existing_token, str):
        tok_mssv = storage.get_json(f"feedtok:{existing_token}")
        if tok_mssv == safe_mssv:
            storage.expire(f"feedtok:{existing_token}", DATA_TTL_SECONDS)
            storage.expire(f"feedtok_by:{safe_mssv}", DATA_TTL_SECONDS)
            return existing_token
    new_token = secrets.token_urlsafe(24)
    storage.set_json(f"feedtok:{new_token}", safe_mssv, ttl=DATA_TTL_SECONDS)
    storage.set_json(f"feedtok_by:{safe_mssv}", new_token, ttl=DATA_TTL_SECONDS)
    build_student_calendar_feed(safe_mssv, new_token)
    return new_token


def regenerate_feed_token(mssv: str) -> str:
    safe_mssv = str(mssv).strip()
    if not safe_mssv:
        return ""
    old_tok = storage.get_json(f"feedtok_by:{safe_mssv}")
    if old_tok and isinstance(old_tok, str):
        storage.delete(f"feedtok:{old_tok}")
        storage.delete(f"feed:{old_tok}")
        storage.delete(f"feed:{old_tok}:all")
        storage.delete(f"feed:{old_tok}:tkb")
        storage.delete(f"feed:{old_tok}:thi")
        storage.delete(f"feed:{old_tok}:han-chot")
    new_token = secrets.token_urlsafe(24)
    storage.set_json(f"feedtok:{new_token}", safe_mssv, ttl=DATA_TTL_SECONDS)
    storage.set_json(f"feedtok_by:{safe_mssv}", new_token, ttl=DATA_TTL_SECONDS)
    build_student_calendar_feed(safe_mssv, new_token)
    return new_token


def get_mssv_by_feed_token(token: str) -> Optional[str]:
    if not token:
        return None
    val = storage.get_json(f"feedtok:{str(token).strip()}")
    if val and isinstance(val, str):
        return val.strip()
    return None


@app.route("/api/calendar/options", methods=["POST"])
def api_calendar_options():
    """Save user calendar feed preferences and rebuild feed variants."""
    session = get_request_session()
    if not session or not session.get("mssv"):
        return jsonify({"success": False, "message": "Yêu cầu đăng nhập tài khoản sinh viên."}), 401
    mssv = str(session["mssv"]).strip()

    if not check_rate_limit(f"rl:feedopt:{mssv}", limit=20, window_sec=60):
        return jsonify({"success": False, "message": "Bạn thực hiện thao tác quá nhanh. Vui lòng thử lại sau giây lát."}), 429

    payload = request.get_json(silent=True) or {}
    reminder_min = payload.get("reminder_min", 20)
    title_style = payload.get("title_style", "name")
    split = bool(payload.get("split", False))
    deadlines = bool(payload.get("deadlines", False))

    try:
        reminder_min = int(reminder_min)
    except (ValueError, TypeError):
        reminder_min = 20

    if reminder_min not in (0, 10, 15, 20, 30, 60):
        return jsonify({"success": False, "message": "Số phút nhắc nhở không hợp lệ."}), 400

    if title_style not in ("name", "code_name"):
        return jsonify({"success": False, "message": "Kiểu hiển thị tiêu đề không hợp lệ."}), 400

    new_options = {
        "reminder_min": reminder_min,
        "title_style": title_style,
        "split": split,
        "deadlines": deadlines,
    }
    save_student_feed_options(mssv, new_options)

    feed_tok = get_or_create_feed_token(mssv)
    build_student_calendar_feed(mssv, feed_tok)

    host_url = request.host_url.rstrip("/")
    is_https = request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"
    if is_https and host_url.startswith("http://"):
        host_url = "https://" + host_url[7:]

    calendars = get_student_calendars_list(feed_tok, new_options, host_url)

    return jsonify({
        "success": True,
        "message": "Đã lưu tuỳ chọn.",
        "options": new_options,
        "calendars": calendars,
    })


@app.route("/api/calendar/feed-token", methods=["GET"])
def api_get_feed_token():
    """Get active secure feed token, subscription URLs, options, and calendar variants."""
    session = get_request_session()
    if not session or not session.get("mssv"):
        return jsonify({"success": False, "message": "Yêu cầu đăng nhập tài khoản sinh viên."}), 401
    mssv = str(session["mssv"]).strip()
    feed_tok = get_or_create_feed_token(mssv)

    # Check pre-built feed record
    feed_data = storage.get_json(f"feed:{feed_tok}:all") or storage.get_json(f"feed:{feed_tok}")
    if not feed_data or not isinstance(feed_data, dict) or not feed_data.get("ics"):
        feed_data = build_student_calendar_feed(mssv, feed_tok)

    updated_at = feed_data.get("updated_at") if feed_data else int(time.time())

    host_url = request.host_url.rstrip("/")
    is_https = request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"
    if is_https and host_url.startswith("http://"):
        host_url = "https://" + host_url[7:]

    template_url = os.environ.get("AUTO_SYNC_TEMPLATE_URL", "").strip()
    options = get_student_feed_options(mssv)
    calendars = get_student_calendars_list(feed_tok, options, host_url)

    return jsonify({
        "success": True,
        "feed_token": feed_tok,
        "feed_url": f"{host_url}/calendar/{feed_tok}/feed.ics",
        "webcal_url": f"webcal://{host_url.split('://', 1)[-1]}/calendar/{feed_tok}/feed.ics",
        "updated_at": updated_at,
        "auto_sync_template_url": template_url,
        "options": options,
        "calendars": calendars,
    })


@app.route("/api/calendar/feed-token/regenerate", methods=["POST"])
def api_regenerate_feed_token():
    """Revoke old feed token and generate a new random feed token for the authenticated student."""
    session = get_request_session()
    if not session or not session.get("mssv"):
        return jsonify({"success": False, "message": "Yêu cầu đăng nhập tài khoản sinh viên."}), 401
    mssv = str(session["mssv"]).strip()

    if not check_rate_limit(f"rl:regen:{mssv}", limit=3, window_sec=3600):
        return jsonify({"success": False, "message": "Bạn chỉ có thể tạo lại liên kết tối đa 3 lần mỗi giờ."}), 429
    new_tok = regenerate_feed_token(mssv)
    host_url = request.host_url.rstrip("/")
    is_https = request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"
    if is_https and host_url.startswith("http://"):
        host_url = "https://" + host_url[7:]

    feed_data = storage.get_json(f"feed:{new_tok}:all") or storage.get_json(f"feed:{new_tok}")
    updated_at = feed_data.get("updated_at") if feed_data else int(time.time())
    options = get_student_feed_options(mssv)
    calendars = get_student_calendars_list(new_tok, options, host_url)

    return jsonify({
        "success": True,
        "feed_token": new_tok,
        "feed_url": f"{host_url}/calendar/{new_tok}/feed.ics",
        "webcal_url": f"webcal://{host_url.split('://', 1)[-1]}/calendar/{new_tok}/feed.ics",
        "updated_at": updated_at,
        "options": options,
        "calendars": calendars,
    })


@app.route("/api/calendar/refresh", methods=["POST"])
def api_calendar_refresh():
    """Manual refresh of student schedule & exams from university portal. Rate-limited to max 1 per 15 min."""
    session = get_request_session()
    if not session or not session.get("mssv"):
        return jsonify({"success": False, "message": "Yêu cầu đăng nhập tài khoản sinh viên."}), 401

    mssv = str(session["mssv"]).strip()
    if not validate_mssv(mssv):
        return jsonify({"success": False, "message": "Mã số sinh viên không hợp lệ."}), 400

    # Rate limit: max 1 request per 15 minutes (900 seconds)
    if not check_rate_limit(f"rl:refresh:{mssv}", limit=1, window_sec=900):
        return jsonify({
            "success": False,
            "message": "Bạn chỉ có thể cập nhật lại từ trường tối đa 1 lần mỗi 15 phút. Vui lòng thử lại sau."
        }), 429

    client = get_session_client(session)
    if not client or not client.ensure_authenticated():
        return jsonify({"success": False, "message": "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại."}), 401

    try:
        def_year, def_term = guess_current_term()
        curr_year = def_year
        curr_term = def_term
        try:
            yt = client.get_year_and_term()
            curr_year = yt.get("CurrentYear") or yt.get("NamHienTai") or curr_year
            curr_term = yt.get("CurrentTerm") or yt.get("HocKyHienTai") or curr_term
            storage.set_json(f"terms_cache:{mssv}", yt, ttl=3600)
        except Exception:
            pass

        format_error = False
        skipped_warning = None

        try:
            raw_sched = client.get_schedule_semester(curr_year, curr_term)
            classes, skipped_classes = parse_semester_schedule(raw_sched)
            if classes:
                save_feed_cache(classes, mssv=mssv)
                if skipped_classes > 0:
                    skipped_warning = f"Có {skipped_classes} buổi chưa đọc được giờ học nên chưa được thêm vào lịch."
        except PortalFormatError:
            format_error = True
        except Exception:
            pass

        try:
            raw_exams = []
            try:
                raw_exams.extend(client.get_exams_by_time())
            except Exception:
                pass
            try:
                raw_exams.extend(client.get_exam_schedule(curr_year, curr_term))
            except Exception:
                pass
            exams, _ = parse_exam_schedule(raw_exams)
            if exams:
                save_cached_exams(exams, mssv=mssv)
        except PortalFormatError:
            format_error = True
        except Exception:
            pass

        if format_error and not load_feed_cache(mssv=mssv):
            return jsonify({"success": False, "message": "Chưa đọc được lịch, bạn thử lại sau."}), 502

        storage.delete(f"overview_cache:{mssv}")
        feed_tok = get_or_create_feed_token(mssv)
        feed_entry = build_student_calendar_feed(mssv, feed_tok)
        updated_at = feed_entry.get("updated_at") if feed_entry else int(time.time())
        touch_student_data_ttl(mssv)

        msg = "Đã cập nhật lịch mới nhất từ trường."
        if skipped_warning:
            msg = f"{msg} {skipped_warning}"

        return jsonify({
            "success": True,
            "updated_at": updated_at,
            "message": msg,
        })
    except Exception as e:
        return jsonify({"success": False, "message": f"Không thể cập nhật từ trường: {e}"}), 500


@app.route("/calendar/<path:category_filename>", methods=["GET"])
@app.route("/calendar/feed.ics", methods=["GET"])
def calendar_feed(category_filename="feed.ics"):
    """
    Live webcal/iCal subscription feed.
    Strictly protected: requires a valid random feed_token in the path: /calendar/<feed_token>/<variant>.ics
    Rejects raw MSSV in URL, rejects ?mssv= query parameter (returns 404).
    Unknown or invalid tokens return 404.
    """
    if request.args.get("mssv"):
        return Response("Not found: Raw MSSV query parameter is deprecated. Please use secure feed token.", status=404, mimetype="text/plain")

    raw_path = (category_filename or "feed.ics").strip("/")
    parts = raw_path.split("/")

    if len(parts) < 2:
        return Response("Not found: Feed token required in URL path /calendar/<feed_token>/feed.ics", status=404, mimetype="text/plain")

    feed_token = parts[0].strip()
    category_file = parts[1].strip().lower()

    # Rate limit: max 60 requests per hour per feed token
    if not check_rate_limit(f"rl:feed:{feed_token}", limit=60, window_sec=3600):
        return Response("Too Many Requests: Rate limit exceeded (max 60/hr).", status=429, mimetype="text/plain")

    # Determine variant from filename
    if category_file in ("feed.ics", "feed", "all.ics", "all"):
        variant = "all"
    elif category_file in ("tkb.ics", "tkb"):
        variant = "tkb"
    elif category_file in ("thi.ics", "thi", "lich_thi.ics"):
        variant = "thi"
    elif category_file in ("han-chot.ics", "han-chot", "deadline.ics", "deadlines.ics"):
        variant = "han-chot"
    else:
        return Response("Lịch không tồn tại hoặc đã hết hạn. Hãy mở UTE-Calendar để lấy lại.", status=404, mimetype="text/plain")

    # 1. Lookup pre-built feed variant in storage
    feed_data = storage.get_json(f"feed:{feed_token}:{variant}")
    if not feed_data or not isinstance(feed_data, dict) or not feed_data.get("ics"):
        # Fallback to general feed record if variant is all
        if variant == "all":
            feed_data = storage.get_json(f"feed:{feed_token}")
        if not feed_data or not isinstance(feed_data, dict) or not feed_data.get("ics"):
            student_mssv = get_mssv_by_feed_token(feed_token)
            if not student_mssv:
                return Response("Lịch không tồn tại hoặc đã hết hạn. Hãy mở UTE-Calendar để lấy lại.", status=404, mimetype="text/plain")
            build_student_calendar_feed(student_mssv, feed_token)
            feed_data = storage.get_json(f"feed:{feed_token}:{variant}") or storage.get_json(f"feed:{feed_token}")
            if not feed_data or not feed_data.get("ics"):
                return Response("Lịch không tồn tại hoặc đã hết hạn. Hãy mở UTE-Calendar để lấy lại.", status=404, mimetype="text/plain")

    ics_content = feed_data.get("ics", "")
    etag = feed_data.get("etag")
    if not etag:
        etag = f'"{hashlib.md5(ics_content.encode("utf-8")).hexdigest()}"'

    is_download = request.args.get("download") in ("1", "true")
    if is_download:
        disposition = f'attachment; filename="ute-calendar-{variant}.ics"'
    else:
        disposition = f'inline; filename="{variant}.ics"'

    headers = {
        "ETag": etag,
        "Cache-Control": "public, max-age=0, s-maxage=3600",
        "Content-Disposition": disposition,
    }

    client_etag = request.headers.get("If-None-Match")
    if client_etag and client_etag.strip() == etag:
        return Response("", status=304, headers=headers)

    return Response(
        ics_content,
        status=200,
        mimetype="text/calendar; charset=utf-8",
        headers=headers,
    )


    # For granular categories (tkb.ics or thi.ics):
    student_mssv = feed_data.get("mssv") or get_mssv_by_feed_token(feed_token)
    if not student_mssv:
        return Response("Not found: Invalid feed token.", status=404, mimetype="text/plain")

    now = get_vietnam_now()
    events = []
    if category_file in ("tkb.ics", "tkb"):
        cached = load_feed_cache(mssv=student_mssv)
        classes = [c for c in cached if (c.event_type or "").upper() in ("CLASS", "TKB")]
        classes.extend(load_makeup_classes(student_mssv))
        cancelled_set = load_cancellations(student_mssv)
        if cancelled_set:
            classes = [c for c in classes if c.uid not in cancelled_set]
        events = [c for c in classes if c.end_datetime >= now]
    elif category_file in ("thi.ics", "thi", "lich_thi.ics"):
        exams = load_cached_exams(mssv=student_mssv)
        events = [ex for ex in exams if ex.start_datetime >= now - timedelta(days=30)]
    else:
        events = []

    if not events:
        ics_content = feed_data.get("ics", "")
        etag = feed_data.get("etag", '""')
        client_etag = request.headers.get("If-None-Match")
        headers = {
            "ETag": etag,
            "Cache-Control": "public, max-age=0, s-maxage=3600",
            "Content-Disposition": f"inline; filename={category_file}",
        }
        if client_etag and client_etag.strip() == etag:
            return Response("", status=304, headers=headers)
        return Response(
            ics_content,
            status=200,
            mimetype="text/calendar; charset=utf-8",
            headers=headers,
        )

    cal_title = f"{APP_NAME} - Lịch học"
    ics_bytes = events_to_ics_bytes(events, calendar_name=cal_title, add_reminders=True)
    etag = f'"{hashlib.md5(ics_bytes).hexdigest()}"'
    client_etag = request.headers.get("If-None-Match")
    headers = {
        "ETag": etag,
        "Cache-Control": "public, max-age=0, s-maxage=3600",
        "Content-Disposition": f"inline; filename={category_file}",
    }
    if client_etag and client_etag.strip() == etag:
        return Response("", status=304, headers=headers)

    return Response(
        ics_bytes,
        status=200,
        mimetype="text/calendar; charset=utf-8",
        headers=headers,
    )





@app.route("/api/schedule/cancel", methods=["POST"])
def api_schedule_cancel():
    """Mark a class session as cancelled manually. Requires student session."""
    session = get_request_session()
    if not session or not session.get("mssv"):
        return jsonify({"success": False, "message": "Yêu cầu đăng nhập tài khoản sinh viên."}), 401

    data = request.json or {}
    uid = data.get("uid", "").strip()
    if not uid:
        return jsonify({"success": False, "message": "Thiếu UID buổi học."}), 400

    mssv = str(session["mssv"]).strip()
    student_events = load_feed_cache(mssv=mssv)
    matching_event = next((e for e in student_events if e.uid == uid), None)
    if not matching_event:
        return jsonify({"success": False, "message": "Buổi học này không nằm trong thời khóa biểu của bạn."}), 400

    add_cancellation(mssv, uid)
    try:
        build_student_calendar_feed(mssv)
    except Exception:
        pass
    return jsonify({
        "success": True,
        "cancelled": list(load_cancellations(mssv)),
    })


@app.route("/api/schedule/uncancel", methods=["POST"])
def api_schedule_uncancel():
    """Unmark a cancelled class. Requires student session."""
    session = get_request_session()
    if not session or not session.get("mssv"):
        return jsonify({"success": False, "message": "Yêu cầu đăng nhập tài khoản sinh viên."}), 401

    data = request.json or {}
    uid = data.get("uid", "").strip()
    if not uid:
        return jsonify({"success": False, "message": "Thiếu UID buổi học."}), 400

    mssv = str(session["mssv"]).strip()
    remove_cancellation(mssv, uid)
    try:
        build_student_calendar_feed(mssv)
    except Exception:
        pass
    return jsonify({
        "success": True,
        "cancelled": list(load_cancellations(mssv)),
    })


@app.route("/api/schedule/makeup", methods=["GET", "POST", "DELETE"])
def api_schedule_makeup():
    """Manage student personal make-up classes."""
    session = get_request_session()
    if not session or not session.get("mssv"):
        return jsonify({"success": False, "message": "Yêu cầu đăng nhập tài khoản sinh viên."}), 401

    mssv = str(session["mssv"]).strip()

    if request.method == "GET":
        events = load_makeup_classes(mssv)
        return jsonify({"success": True, "items": [e.to_dict() for e in events]})

    if request.method == "POST":
        data = request.json or {}
        title = data.get("title", "").strip()
        date_str = data.get("date", "").strip()
        start_time_str = data.get("start_time", "07:30").strip()
        end_time_str = data.get("end_time", "").strip()
        location = data.get("location", "HCMUTE").strip()
        note = data.get("note", "").strip()

        if not title or not date_str:
            return jsonify({"success": False, "message": "Vui lòng nhập Tên môn học và Ngày học bù."}), 400

        try:
            m_d = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", date_str)
            if m_d:
                day, month, year = int(m_d.group(1)), int(m_d.group(2)), int(m_d.group(3))
            else:
                m_iso = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str)
                if m_iso:
                    year, month, day = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
                else:
                    return jsonify({"success": False, "message": "Định dạng ngày không hợp lệ. Dùng dd/mm/yyyy hoặc yyyy-mm-dd."}), 400

            m_t = re.search(r"(\d{1,2})[:gh](\d{2})", start_time_str)
            shh = int(m_t.group(1)) if m_t else 7
            smm = int(m_t.group(2)) if m_t else 30
            st = datetime(year, month, day, shh, smm)

            if end_time_str:
                m_et = re.search(r"(\d{1,2})[:gh](\d{2})", end_time_str)
                ehh = int(m_et.group(1)) if m_et else shh + 3
                emm = int(m_et.group(2)) if m_et else smm + 45
                en = datetime(year, month, day, ehh, emm)
            else:
                en = st + timedelta(hours=3, minutes=45)

            ev = add_makeup_class(mssv, title, st, en, location=location, note=note)
            return jsonify({"success": True, "event": ev.to_dict()})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 400

    if request.method == "DELETE":
        data = request.json or {}
        uid = data.get("uid", "").strip()
        if not uid:
            return jsonify({"success": False, "message": "Thiếu UID buổi học bù."}), 400
        ok = remove_makeup_class(mssv, uid)
        return jsonify({"success": ok})


def run_app(port: int = None, open_browser: bool = True):
    if port is None:
        port = int(os.environ.get("PORT", 5000))

    is_cloud = bool(os.environ.get("PORT"))
    host = "0.0.0.0" if is_cloud else "127.0.0.1"
    url = f"http://localhost:{port}"

    # Zero background bot daemons

    if open_browser and not is_cloud and not os.environ.get("NO_BROWSER"):
        Timer(1.2, lambda: webbrowser.open(url)).start()

    print(f"\nUTE-Calendar đang chạy tại: http://{host}:{port}\n")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    run_app()
