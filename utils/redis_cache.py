"""Optional Redis-backed JSON cache with safe in-process fallback.

Redis is intentionally an optional acceleration layer. When ``REDIS_URL`` is
unset or Redis is unavailable, callers continue using the database/filesystem
without changing application behaviour.
"""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from typing import Any

from loguru import logger
import redis


_DEFAULT_PREFIX = "daiboo"
_DEFAULT_TTL = 300


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def redis_url() -> str | None:
    value = os.getenv("REDIS_URL") or os.getenv("DAIBOO_REDIS_URL")
    value = (value or "").strip()
    return value or None


def _prefix() -> str:
    return (os.getenv("REDIS_CACHE_PREFIX", _DEFAULT_PREFIX).strip() or _DEFAULT_PREFIX)


@lru_cache(maxsize=1)
def get_redis_client() -> redis.Redis | None:
    """Return one lazy Redis client, or ``None`` when caching is disabled."""
    url = redis_url()
    if not url:
        return None
    try:
        return redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=_env_float("REDIS_CONNECT_TIMEOUT", 0.2),
            socket_timeout=_env_float("REDIS_SOCKET_TIMEOUT", 0.2),
            health_check_interval=30,
        )
    except Exception:
        logger.exception("Failed to configure Redis cache client")
        return None


def cache_enabled() -> bool:
    return redis_url() is not None


def cache_key(namespace: str, *parts: Any) -> str:
    """Build a bounded, non-user-controlled Redis key."""
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    safe_namespace = "".join(char if char.isalnum() or char in "-_" else "_" for char in namespace)
    return f"{_prefix()}:{safe_namespace}:{digest}"


def _json_loads(value: Any) -> Any | None:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def get_json(key: str) -> Any | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        return _json_loads(client.get(key))
    except Exception:
        logger.debug("Redis cache read failed for key {}", key)
        return None


def set_json(key: str, value: Any, *, ttl: int = _DEFAULT_TTL) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.set(key, json.dumps(value, ensure_ascii=False, separators=(",", ":")), ex=max(1, int(ttl)))
        return True
    except Exception:
        logger.debug("Redis cache write failed for key {}", key)
        return False


def delete(*keys: str) -> bool:
    if not keys:
        return True
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.delete(*keys)
        return True
    except Exception:
        logger.debug("Redis cache delete failed")
        return False


def _namespace_version_key(namespace: str) -> str:
    return f"{_prefix()}:namespace:{namespace}:version"


def namespace_version(namespace: str) -> int:
    client = get_redis_client()
    if client is None:
        return 0
    try:
        value = client.get(_namespace_version_key(namespace))
        return int(value or 0)
    except Exception:
        logger.debug("Redis namespace version read failed for {}", namespace)
        return 0


def bump_namespace(namespace: str) -> int:
    client = get_redis_client()
    if client is None:
        return 0
    try:
        return int(client.incr(_namespace_version_key(namespace)))
    except Exception:
        logger.debug("Redis namespace version bump failed for {}", namespace)
        return 0


def versioned_cache_key(kind: str, namespace: str, *parts: Any) -> str:
    return cache_key(kind, namespace_version(namespace), *parts)


def cache_status() -> dict[str, bool]:
    """Return configuration and live availability without raising to callers."""
    if not cache_enabled():
        return {"configured": False, "available": False}
    client = get_redis_client()
    if client is None:
        return {"configured": True, "available": False}
    try:
        client.ping()
    except Exception:
        return {"configured": True, "available": False}
    return {"configured": True, "available": True}
