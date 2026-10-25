"""
Persistent Storage Engine with Upstash Redis REST and Local-File Fallback.
Provides unified, thread-safe, resilient key-value, set, and hash operations:
- get_json / set_json / delete
- set_nx (atomic SET with NX and EX)
- sadd / srem / scard / smembers (Redis Sets for concurrency-safe collections)
- hget / hset / hdel / hgetall (Redis Hashes for structured entity storage)
- incr_with_ttl (Atomic counter with expiration for rate-limiting & metrics)
- pipeline (Batch multi-command execution via Upstash /pipeline endpoint)

Architecture:
- When UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN are set:
  Redis is the SINGLE SOURCE OF TRUTH. Never falls back to disk on network errors.
- When running in Vercel environment without Redis credentials:
  Raises RuntimeError immediately on import (Fail-Fast) to ensure data is never lost silently.
- When running on Localhost without Redis credentials:
  Falls back to thread-safe local file storage in data/.storage.
"""

import os
import sys
import json
import time
import urllib.parse
import threading
from typing import Any, Optional, Set, List, Dict, Tuple
import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE_DATA_DIR = os.environ.get(
    "DATA_DIR",
    "/tmp/data" if os.environ.get("VERCEL") else os.path.join(PROJECT_ROOT, "data")
)
LOCAL_STORAGE_DIR = os.path.join(BASE_DATA_DIR, ".storage")

_LOCAL_LOCK = threading.RLock()
_HTTP_SESSION = requests.Session()


def _get_upstash_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Retrieve Upstash Redis REST URL and Token from environment."""
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "").strip().rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
    if url and token:
        return url, token
    return None, None


# Fail-fast check on Vercel
if os.environ.get("VERCEL") and not is_redis_available() if "is_redis_available" in locals() else (os.environ.get("VERCEL") and not (_get_upstash_credentials()[0] and _get_upstash_credentials()[1])):
    # Check if testing or deployment
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError(
            "CRITICAL: UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN are required on Vercel. "
            "Please configure them in Vercel Project Settings -> Environment Variables."
        )


def is_redis_available() -> bool:
    """Return True if Upstash Redis credentials are configured in environment."""
    url, token = _get_upstash_credentials()
    return bool(url and token)


def _exec_redis(command_tokens: List[Any], timeout: float = 3.0) -> Tuple[bool, Optional[Any]]:
    """
    Execute a raw command array against Upstash Redis REST endpoint.
    Strict timeout (default 3.0s); catches all network/HTTP errors.
    Returns: (ok: bool, result: Any).
    - If successful: (True, data.get("result"))
    - If network/HTTP error or Redis error: (False, None)
    Never raises into callers.
    """
    url, token = _get_upstash_credentials()
    if not url or not token:
        return False, None

    try:
        resp = _HTTP_SESSION.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=command_tokens,
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                if "error" in data:
                    print(f"[Storage Redis Warning] {data.get('error')}")
                    return False, None
                return True, data.get("result")
        return False, None
    except Exception as e:
        print(f"[Storage Redis Request Error] {e}")
        return False, None


def pipeline(commands: List[List[Any]], timeout: float = 5.0) -> Tuple[bool, List[Any]]:
    """
    Execute multiple Redis commands in a single HTTP request via Upstash /pipeline endpoint.
    Returns: (ok: bool, results: List[Any]).
    """
    url, token = _get_upstash_credentials()
    if not url or not token:
        return False, []

    pipe_url = f"{url}/pipeline"
    try:
        resp = _HTTP_SESSION.post(
            pipe_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=commands,
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                results = []
                for item in data:
                    if isinstance(item, dict) and "result" in item:
                        results.append(item.get("result"))
                    else:
                        results.append(None)
                return True, results
        return False, []
    except Exception as e:
        print(f"[Storage Redis Pipeline Error] {e}")
        return False, []


def ping() -> bool:
    """Check connectivity to Upstash Redis with a fast 2-second timeout."""
    if not is_redis_available():
        return False
    ok, res = _exec_redis(["PING"], timeout=2.0)
    return bool(ok and res in ("PONG", True))


# ==================== Local File Fallback Engine (Localhost Only) ====================


def _get_local_file_path(key: str) -> str:
    """Derive safe filename from key using URL encoding."""
    safe_name = urllib.parse.quote(str(key), safe="")
    return os.path.join(LOCAL_STORAGE_DIR, f"{safe_name}.json")


def _read_local_entry(key: str) -> Optional[dict]:
    path = _get_local_file_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        exp = data.get("exp")
        if exp is not None and time.time() > float(exp):
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        return data
    except Exception:
        return None


def _write_local_entry(key: str, val_payload: Any, ttl: Optional[int] = None) -> bool:
    try:
        os.makedirs(LOCAL_STORAGE_DIR, exist_ok=True)
        path = _get_local_file_path(key)
        exp = (time.time() + float(ttl)) if ttl and ttl > 0 else None
        record = {"val": val_payload, "exp": exp}
        tmp = f"{path}.tmp.{os.getpid()}.{time.time()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"[Storage Local Write Error] {e}")
        return False


# ==================== Unified Public Storage API ====================


def get_json(key: str, default: Any = None) -> Any:
    """Retrieve JSON-deserialized object from persistent storage."""
    if is_redis_available():
        ok, res = _exec_redis(["GET", str(key)])
        if ok and res is not None:
            try:
                return json.loads(res) if isinstance(res, str) else res
            except Exception:
                return default
        return default

    # Local file fallback (when Redis env vars absent)
    with _LOCAL_LOCK:
        entry = _read_local_entry(str(key))
        if entry is not None:
            return entry.get("val", default)
        return default


def set_json(key: str, value: Any, ttl: Optional[int] = None) -> bool:
    """Persist JSON-serializable object with optional TTL in seconds."""
    if is_redis_available():
        try:
            val_str = json.dumps(value, ensure_ascii=False)
        except Exception:
            return False
        if ttl and int(ttl) > 0:
            cmd = ["SET", str(key), val_str, "EX", int(ttl)]
        else:
            cmd = ["SET", str(key), val_str]
        ok, res = _exec_redis(cmd)
        return bool(ok and res in ("OK", True))

    with _LOCAL_LOCK:
        return _write_local_entry(str(key), value, ttl=ttl)


def delete(key: str) -> bool:
    """Delete a key from persistent storage."""
    if is_redis_available():
        ok, _ = _exec_redis(["DEL", str(key)])
        return ok

    with _LOCAL_LOCK:
        path = _get_local_file_path(str(key))
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except OSError:
                return False
        return True


def expire(key: str, ttl: int) -> bool:
    """Set or refresh TTL in seconds for an existing key."""
    if not key or not ttl or int(ttl) <= 0:
        return False
    if is_redis_available():
        ok, res = _exec_redis(["EXPIRE", str(key), int(ttl)])
        return bool(ok and res in (1, "1", True))

    with _LOCAL_LOCK:
        entry = _read_local_entry(str(key))
        if entry is None:
            return False
        return _write_local_entry(str(key), entry.get("val"), ttl=int(ttl))


def set_nx(key: str, value: Any = "1", ttl: Optional[int] = None) -> bool:
    """
    Atomic SET IF NOT EXISTS (SET NX).
    Returns True if key was set; False if key already exists or network error.
    """
    if is_redis_available():
        val_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        if ttl and int(ttl) > 0:
            cmd = ["SET", str(key), val_str, "EX", int(ttl), "NX"]
        else:
            cmd = ["SET", str(key), val_str, "NX"]
        ok, res = _exec_redis(cmd)
        # Upstash returns "OK" when key was set, null when key already existed
        return bool(ok and res == "OK")

    with _LOCAL_LOCK:
        existing = _read_local_entry(str(key))
        if existing is not None:
            return False
        return _write_local_entry(str(key), value, ttl=ttl)


def sadd(key: str, *members: Any, ttl: Optional[int] = None) -> int:
    """Add one or more members to a Redis Set with optional TTL."""
    valid_members = [str(m) for m in members if m is not None]
    if not valid_members:
        return 0

    if is_redis_available():
        cmd = ["SADD", str(key)] + valid_members
        ok, res = _exec_redis(cmd)
        if ttl and int(ttl) > 0:
            _exec_redis(["EXPIRE", str(key), int(ttl)])
        return int(res) if (ok and isinstance(res, (int, float))) else 0

    with _LOCAL_LOCK:
        entry = _read_local_entry(str(key))
        cur_set = set(entry.get("val", [])) if entry else set()
        orig_len = len(cur_set)
        for m in valid_members:
            cur_set.add(m)
        added = len(cur_set) - orig_len
        cur_ttl = ttl if ttl is not None else (int(entry["exp"] - time.time()) if (entry and entry.get("exp")) else None)
        _write_local_entry(str(key), sorted(list(cur_set)), ttl=cur_ttl)
        return added


def srem(key: str, *members: Any, ttl: Optional[int] = None) -> int:
    """Remove one or more members from a Redis Set with optional TTL."""
    valid_members = [str(m) for m in members if m is not None]
    if not valid_members:
        return 0

    if is_redis_available():
        cmd = ["SREM", str(key)] + valid_members
        ok, res = _exec_redis(cmd)
        if ttl and int(ttl) > 0:
            _exec_redis(["EXPIRE", str(key), int(ttl)])
        return int(res) if (ok and isinstance(res, (int, float))) else 0

    with _LOCAL_LOCK:
        entry = _read_local_entry(str(key))
        if not entry:
            return 0
        cur_set = set(entry.get("val", []))
        orig_len = len(cur_set)
        for m in valid_members:
            cur_set.discard(m)
        removed = orig_len - len(cur_set)
        cur_ttl = ttl if ttl is not None else (int(entry["exp"] - time.time()) if (entry and entry.get("exp")) else None)
        _write_local_entry(str(key), sorted(list(cur_set)), ttl=cur_ttl)
        return removed


def scard(key: str) -> int:
    """Return the number of elements in a Redis Set."""
    if is_redis_available():
        ok, res = _exec_redis(["SCARD", str(key)])
        return int(res) if (ok and isinstance(res, (int, float))) else 0

    with _LOCAL_LOCK:
        entry = _read_local_entry(str(key))
        if not entry:
            return 0
        return len(entry.get("val", []))


def smembers(key: str) -> Set[str]:
    """Return all members in a Redis Set as a Python set of strings."""
    if is_redis_available():
        ok, res = _exec_redis(["SMEMBERS", str(key)])
        if ok and isinstance(res, list):
            return {str(m) for m in res}
        return set()

    with _LOCAL_LOCK:
        entry = _read_local_entry(str(key))
        if not entry:
            return set()
        return {str(m) for m in entry.get("val", [])}


def hset(key: str, field: str, value: Any) -> bool:
    """Set field in a Redis Hash."""
    val_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if is_redis_available():
        ok, _ = _exec_redis(["HSET", str(key), str(field), val_str])
        return ok

    with _LOCAL_LOCK:
        entry = _read_local_entry(str(key))
        d = dict(entry.get("val", {})) if entry and isinstance(entry.get("val"), dict) else {}
        d[str(field)] = value
        return _write_local_entry(str(key), d)


def hget(key: str, field: str, default: Any = None) -> Any:
    """Get field from a Redis Hash."""
    if is_redis_available():
        ok, res = _exec_redis(["HGET", str(key), str(field)])
        if ok and res is not None:
            try:
                return json.loads(res) if isinstance(res, str) else res
            except Exception:
                return res
        return default

    with _LOCAL_LOCK:
        entry = _read_local_entry(str(key))
        if entry and isinstance(entry.get("val"), dict):
            return entry["val"].get(str(field), default)
        return default


def hdel(key: str, field: str) -> bool:
    """Delete field from a Redis Hash."""
    if is_redis_available():
        ok, _ = _exec_redis(["HDEL", str(key), str(field)])
        return ok

    with _LOCAL_LOCK:
        entry = _read_local_entry(str(key))
        if entry and isinstance(entry.get("val"), dict):
            d = dict(entry["val"])
            d.pop(str(field), None)
            return _write_local_entry(str(key), d)
        return True


def hgetall(key: str) -> Dict[str, Any]:
    """Get all field-value pairs from a Redis Hash as a dictionary."""
    if is_redis_available():
        ok, res = _exec_redis(["HGETALL", str(key)])
        if ok and res:
            out = {}
            if isinstance(res, list):
                # Upstash may return [field1, val1, field2, val2...]
                for i in range(0, len(res), 2):
                    f = str(res[i])
                    v = res[i + 1] if i + 1 < len(res) else ""
                    try:
                        out[f] = json.loads(v) if isinstance(v, str) else v
                    except Exception:
                        out[f] = v
            elif isinstance(res, dict):
                for f, v in res.items():
                    try:
                        out[str(f)] = json.loads(v) if isinstance(v, str) else v
                    except Exception:
                        out[str(f)] = v
            return out
        return {}

    with _LOCAL_LOCK:
        entry = _read_local_entry(str(key))
        if entry and isinstance(entry.get("val"), dict):
            return dict(entry["val"])
        return {}


def incr_with_ttl(key: str, ttl: int = 600) -> int:
    """
    Atomically increment key and ensure TTL is set (INCR + EXPIRE NX).
    Used for rate limiting and anonymous access counting.
    """
    if is_redis_available():
        # Upstash bills per command: INCR alone is 1, and EXPIRE is only needed when the key was just created.
        ok, count = _exec_redis(["INCR", str(key)])
        if ok and isinstance(count, (int, float)):
            if int(count) == 1:
                _exec_redis(["EXPIRE", str(key), int(ttl)])
            return int(count)
        return 1

    with _LOCAL_LOCK:
        entry = _read_local_entry(str(key))
        curr = int(entry.get("val", 0)) if entry and isinstance(entry.get("val"), (int, float)) else 0
        new_val = curr + 1
        _write_local_entry(str(key), new_val, ttl=ttl)
        return new_val
