import json

import pytest


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.expirations = {}
        self.fail = False

    def get(self, key):
        if self.fail:
            raise RuntimeError("redis unavailable")
        return self.data.get(key)

    def set(self, key, value, ex=None):
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.data[key] = value
        self.expirations[key] = ex
        return True

    def delete(self, *keys):
        if self.fail:
            raise RuntimeError("redis unavailable")
        deleted = 0
        for key in keys:
            if key in self.data:
                deleted += 1
                self.data.pop(key)
        return deleted

    def incr(self, key):
        if self.fail:
            raise RuntimeError("redis unavailable")
        value = int(self.data.get(key, 0)) + 1
        self.data[key] = str(value)
        return value

    def ping(self):
        if self.fail:
            raise RuntimeError("redis unavailable")
        return True


def test_cache_is_disabled_without_redis_url(monkeypatch):
    from utils import redis_cache

    monkeypatch.delenv("REDIS_URL", raising=False)
    redis_cache.get_redis_client.cache_clear()

    assert redis_cache.cache_enabled() is False
    assert redis_cache.get_json("missing") is None
    assert redis_cache.set_json("key", {"ok": True}, ttl=30) is False
    assert redis_cache.cache_status() == {"configured": False, "available": False}


def test_json_round_trip_and_ttl(monkeypatch):
    from utils import redis_cache

    fake = FakeRedis()
    monkeypatch.setattr(redis_cache, "get_redis_client", lambda: fake)

    payload = {"message": "你好", "items": [1, 2, 3]}
    assert redis_cache.set_json("daiboo:test", payload, ttl=45) is True
    assert redis_cache.get_json("daiboo:test") == payload
    assert fake.expirations["daiboo:test"] == 45
    assert json.loads(fake.data["daiboo:test"]) == payload


def test_cache_failures_degrade_to_misses(monkeypatch):
    from utils import redis_cache

    fake = FakeRedis()
    fake.fail = True
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/0")
    monkeypatch.setattr(redis_cache, "get_redis_client", lambda: fake)

    assert redis_cache.get_json("key") is None
    assert redis_cache.set_json("key", {"ok": True}, ttl=10) is False
    assert redis_cache.delete("key") is False
    assert redis_cache.cache_status() == {"configured": True, "available": False}


def test_namespace_version_invalidates_versioned_keys(monkeypatch):
    from utils import redis_cache

    fake = FakeRedis()
    monkeypatch.setattr(redis_cache, "get_redis_client", lambda: fake)

    assert redis_cache.namespace_version("rag") == 0
    before = redis_cache.versioned_cache_key("rag-search", "rag", "hello", 5, True)
    assert redis_cache.bump_namespace("rag") == 1
    after = redis_cache.versioned_cache_key("rag-search", "rag", "hello", 5, True)

    assert before != after
    assert before.startswith("daiboo:rag-search:")
    assert after.startswith("daiboo:rag-search:")


def test_cache_keys_hash_untrusted_parts():
    from utils.redis_cache import cache_key

    key = cache_key("chat-session", "../../secret/session id")

    assert key.startswith("daiboo:chat-session:")
    assert "secret" not in key
    assert "../" not in key
