"""Native Jev HTTP contract tests: only a real loopback server, never inference."""

import asyncio
from copy import deepcopy
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from utils.typesafe_client import (
    ChoiceQuestion,
    JevClient,
    JevQuestion,
    NoulQuestion,
    ScoreQuestion,
    jev_enabled,
)

KEY = "test-local-only-token"
STATE = {"page": "A private test page", "items": [1, True, None]}
QUESTIONS = {
    "urgent": {"type": "noul", "instructions": "Is this urgent?"},
    "route": {
        "type": "choice", "instructions": {"question": "Where?"},
        "criteria": {"support": "Help", "other": {"means": "Not help"}},
    },
    "rating": {"type": "score", "instructions": "Severity?", "criteria": ["Low", "High"]},
}
RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "urgent": {"type": "noul", "noul": 0.9},
        "route": {
            "type": "choice", "choice": "support",
            "probabilities": {"support": 0.8, "other": 0.2}, "confidence": 0.6,
        },
        "rating": {
            "type": "score", "score": 0.75, "legend": {"0": "Low", "1": "High"},
            "probabilities": {"0": 0.25, "1": 0.75}, "confidence": 0.5,
        },
    },
    "usage": {"input_tokens": 123, "output_tokens": 0},
}


@contextmanager
def server(*, body=None, raw=None, status=200, delay: float = 0, headers=None, chunk_delay: float = 0):
    """HTTP/1.1 server records peer ports to prove connection reuse."""
    records = []
    seen = threading.Event()
    payload = raw if raw is not None else json.dumps(RESPONSE if body is None else body).encode()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            request_body = self.rfile.read(int(self.headers["Content-Length"]))
            records.append({
                "path": self.path, "body": json.loads(request_body),
                "headers": dict(self.headers), "peer": self.client_address,
            })
            seen.set()
            time.sleep(delay)
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                if chunk_delay:
                    step = max(1, len(payload) // 10)
                    for offset in range(0, len(payload), step):
                        self.wfile.write(payload[offset:offset + step])
                        self.wfile.flush()
                        time.sleep(chunk_delay)
                else:
                    self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    # The short polling interval keeps parameterized contract tests fast.
    thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/v1", records, seen
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    # No .env is loaded; requests cannot reach a real inference provider.
    for name in ("TYPESAFE_API_KEY", "TYPESAFE_BASE_URL", "TYPESAFE_MODEL", "TYPESAFE_TIMEOUT_SECONDS", "DAIBOO_JEV_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


def test_question_models_and_discriminated_union():
    adapter = TypeAdapter(JevQuestion)
    assert isinstance(adapter.validate_python(QUESTIONS["urgent"]), NoulQuestion)
    assert isinstance(adapter.validate_python(QUESTIONS["route"]), ChoiceQuestion)
    assert isinstance(adapter.validate_python(QUESTIONS["rating"]), ScoreQuestion)
    question = NoulQuestion(instructions="Yes?", criteria={"true": "Yes", "false": ["No"]})
    assert question.type == "noul"
    assert question.model_dump(exclude_none=True)["criteria"] == {"true": "Yes", "false": ["No"]}


@pytest.mark.parametrize("question", [
    {"type": "box", "instructions": "Find it"},
    {"type": "noul", "instructions": "?", "assets": []},
    {"type": "noul", "instructions": "?", "criteria": {"maybe": "maybe"}},
    {"type": "noul", "instructions": "?", "criteria": {True: "yes"}},
    {"type": "noul", "instructions": "?", "criteria": {"true": None}},
    {"type": "noul", "instructions": ""},
    {"type": "noul", "instructions": " "},
    {"type": "noul", "instructions": 1},
    {"type": "noul", "instructions": {"bad": float("nan")}},
    {"type": "noul", "instructions": "x" * 8001},
    {"type": "choice", "instructions": "?", "criteria": {"only": "one"}},
    {"type": "choice", "instructions": "?", "criteria": {"": "empty", "a": "a"}},
    {"type": "choice", "instructions": "?", "criteria": {1: "a", "1": "b"}},
    {"type": "choice", "instructions": "?", "criteria": {str(i): "x" for i in range(33)}},
    {"type": "choice", "instructions": "?", "criteria": {"a": None, "b": "b"}},
    {"type": "score", "instructions": "?", "criteria": ["one"]},
    {"type": "score", "instructions": "?", "criteria": ["x"] * 11},
    {"type": "score", "instructions": "?", "criteria": ["x", None]},
    {"type": "score", "instructions": "?", "criteria": ("x", "y")},
])
def test_question_rejects_invalid_and_unsupported(question):
    with pytest.raises(ValidationError):
        TypeAdapter(JevQuestion).validate_python(question)


@pytest.mark.parametrize("value,expected", [(None, False), ("true", True), ("1", True), ("false", False), ("0", False), ("invalid", False)])
def test_feature_gate(monkeypatch, value, expected):
    if value is not None:
        monkeypatch.setenv("DAIBOO_JEV_ENABLED", value)
    assert jev_enabled() is expected


def test_configuration_is_lazy_defaults_and_redacted(monkeypatch):
    with pytest.raises(ValueError, match="configuration"):
        JevClient.from_env()
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)
    client = JevClient.from_env()
    assert client.base_url == "https://api.typesafe.ai/v1"
    assert client.model == "jev-latest"
    assert client.timeout == 10
    assert KEY not in repr(client)
    assert getattr(client, "_client", None) is None
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://127.0.0.1:12345/v1")
    monkeypatch.setenv("TYPESAFE_MODEL", "jev-preview")
    monkeypatch.setenv("TYPESAFE_TIMEOUT_SECONDS", "2.5")
    client = JevClient.from_env()
    assert (client.base_url, client.model, client.timeout) == ("http://127.0.0.1:12345/v1", "jev-preview", 2.5)


@pytest.mark.parametrize("overrides", [
    {"api_key": ""}, {"api_key": "\nsecret"}, {"api_key": " secret "},
    {"timeout": 0}, {"timeout": -1}, {"timeout": 61}, {"timeout": float("inf")},
    {"timeout": float("nan")}, {"timeout": True}, {"timeout": "bad"},
    {"base_url": "https://user:secret@example.com/v1"},
    {"base_url": "https://example.com/v1?key=secret"},
    {"base_url": "https://example.com/v1#secret"},
    {"base_url": "http://example.com/v1"}, {"base_url": "file:///v1"},
    {"base_url": "https://example.com/v1/systemone"},
    {"model": ""}, {"model": " jev-latest "},
])
def test_bad_configuration_is_fixed_error(overrides):
    config = {"api_key": KEY, **overrides}
    with pytest.raises(ValueError) as caught:
        JevClient(**config)
    assert str(caught.value) == "Invalid Jev configuration."
    assert KEY not in str(caught.value)
    assert "secret" not in str(caught.value)


async def test_native_request_projection_reuse_and_close():
    response = deepcopy(RESPONSE)
    response["private"] = "discard me"
    response["usage"]["details"] = "discard me"
    response["answers"]["route"]["explanation"] = "discard me"
    with server(body=response) as (url, records, _):
        client = JevClient(api_key=KEY, base_url=url)
        typed = {name: TypeAdapter(JevQuestion).validate_python(question) for name, question in QUESTIONS.items()}
        try:
            first = await client.evaluate(state=STATE, questions=typed)
            second = await client.evaluate(state=STATE, questions=QUESTIONS)
            assert first["ok"] is True
            assert {key: first[key] for key in RESPONSE} == RESPONSE
            assert "private" not in first
            assert second["ok"] is True
            assert len(records) == 2
            assert records[0]["peer"] == records[1]["peer"]
            assert records[0]["path"] == "/v1/systemone"
            assert records[0]["body"] == {"state": STATE, "model": "jev-latest", "questions": QUESTIONS}
            headers = {key.lower(): value for key, value in records[0]["headers"].items()}
            assert headers["authorization"] == f"Bearer {KEY}"
            assert headers["content-type"].startswith("application/json")
            assert not any("longcontext" in key or "long-context" in key for key in headers)
            assert KEY not in json.dumps(records[0]["body"])
            transport = client._client
            assert isinstance(transport, httpx.AsyncClient)
            assert transport.follow_redirects is False
        finally:
            await client.aclose()
            await client.aclose()
        assert transport.is_closed
        assert (await client.evaluate(state=STATE, questions=QUESTIONS))["reason"] == "closed"


@pytest.mark.parametrize("state", [None, "", "  ", {}, [], 1, True, ("tuple",), b"image", {1: "bad"},
    {"x": float("nan")}, {"x": float("inf")}, {"x": 10**400}, {"x": object()},
    {"type": "image", "url": "https://example.com/image.png"}, "x" * 48001])
async def test_invalid_state_does_not_send(state):
    with server() as (url, records, _):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            result = await client.evaluate(state=state, questions=QUESTIONS)
            assert result["ok"] is False
            assert result["reason"] == "invalid_input"
            assert records == []
            assert client._client is None
        finally:
            await client.aclose()


@pytest.mark.parametrize("questions", [{}, {"": QUESTIONS["urgent"]}, {" ": QUESTIONS["urgent"]},
    {1: QUESTIONS["urgent"]}, {str(i): QUESTIONS["urgent"] for i in range(13)},
    {"q": {"type": "box", "instructions": "Find"}}, {"q": {"type": "noul", "instructions": "?", "images": []}}])
async def test_invalid_questions_do_not_send(questions):
    with server() as (url, records, _):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            result = await client.evaluate(state=STATE, questions=questions)
            assert result["reason"] == "invalid_input"
            assert records == []
        finally:
            await client.aclose()


async def test_nested_cycle_and_mutated_model_are_revalidated():
    deep = "leaf"
    for _ in range(20):
        deep = [deep]
    cycle = []
    cycle.append(cycle)
    model = NoulQuestion(instructions="Fine")
    model.instructions = ""
    with server() as (url, records, _):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            for state in (deep, cycle):
                assert (await client.evaluate(state=state, questions=QUESTIONS))["reason"] == "invalid_input"
            assert (await client.evaluate(state=STATE, questions={"q": model}))["reason"] == "invalid_input"
            assert records == []
        finally:
            await client.aclose()


async def test_structured_score_legend_is_preserved_and_ties_allowed():
    questions = deepcopy(QUESTIONS)
    questions["rating"]["criteria"] = [{"meaning": "Low", "examples": ["Minor"]}, ["High"]]
    response = deepcopy(RESPONSE)
    response["answers"]["rating"]["legend"] = dict(enumerate(questions["rating"]["criteria"]))
    response["answers"]["route"].update(probabilities={"support": 0.5, "other": 0.5}, confidence=0)
    with server(body=response) as (url, _, _):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            result = await client.evaluate(state=STATE, questions=questions)
            assert result["ok"] is True
            assert result["answers"]["rating"]["legend"] == {"0": questions["rating"]["criteria"][0], "1": ["High"]}
        finally:
            await client.aclose()


# Path replacements exercise each mandatory response field without source-string checks.
BAD_RESPONSES = [
    (("model",), ""), (("answers",), {}), (("answers", "extra"), {"type": "noul", "noul": 1}),
    (("answers", "urgent", "type"), "choice"),
    *(((("answers", "urgent", "noul"), value)) for value in [True, -0.1, 1.1, "0.9", None, float("nan"), float("inf")]),
    (("answers", "route", "choice"), "unknown"), (("answers", "route", "choice"), "other"),
    (("answers", "route", "probabilities"), {"support": 1.0}),
    (("answers", "route", "probabilities"), {"support": 0.8, "other": 0.1}),
    (("answers", "route", "probabilities"), {"support": 0.8, "other": 0.2, "extra": 0}),
    (("answers", "route", "probabilities"), {"support": True, "other": 0}),
    (("answers", "route", "probabilities"), {"support": 1.1, "other": -0.1}),
    (("answers", "route", "confidence"), True), (("answers", "route", "confidence"), 1.1),
    (("answers", "rating", "legend"), {"1": "Low", "2": "High"}),
    (("answers", "rating", "legend"), {"0": "Wrong", "1": "High"}),
    (("answers", "rating", "probabilities"), {"1": 0.25, "2": 0.75}),
    (("answers", "rating", "score"), 0.2), (("answers", "rating", "score"), 1.1),
    (("answers", "rating", "score"), True), (("answers", "rating", "confidence"), -0.1),
    (("usage", "input_tokens"), True), (("usage", "input_tokens"), -1),
    (("usage", "input_tokens"), 1.2), (("usage", "input_tokens"), "12"),
]


@pytest.mark.parametrize("path,value", BAD_RESPONSES)
async def test_malformed_upstream_response_is_rejected(path, value):
    response = deepcopy(RESPONSE)
    target = response
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with server(body=response) as (url, records, _):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            result = await client.evaluate(state=STATE, questions=QUESTIONS)
            assert result["ok"] is False
            assert result["reason"] == "invalid_response"
            assert len(records) == 1
            assert STATE["page"] not in json.dumps(result)
            assert KEY not in json.dumps(result)
        finally:
            await client.aclose()


@pytest.mark.parametrize("path", [("model",), ("usage",), ("usage", "output_tokens"),
    ("answers", "urgent", "noul"), ("answers", "route", "confidence"),
    ("answers", "rating", "legend"), ("answers", "rating", "probabilities"), ("answers", "rating", "score")])
async def test_missing_upstream_fields_are_not_invented(path):
    response = deepcopy(RESPONSE)
    target = response
    for part in path[:-1]:
        target = target[part]
    del target[path[-1]]
    with server(body=response) as (url, _, _):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            assert (await client.evaluate(state=STATE, questions=QUESTIONS))["reason"] == "invalid_response"
        finally:
            await client.aclose()


@pytest.mark.parametrize("raw", [b"not json", b"[]", b'{"model":"a","model":"b"}',
    b'{"model":"jev","answers":{"urgent":{"type":"noul","noul":0,"noul":1}},"usage":{"input_tokens":0,"output_tokens":0}}'])
async def test_invalid_json_and_duplicate_wire_keys_are_rejected(raw):
    with server(raw=raw) as (url, _, _):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            assert (await client.evaluate(state=STATE, questions=QUESTIONS))["reason"] == "invalid_response"
        finally:
            await client.aclose()


@pytest.mark.parametrize("status,reason", [(400, "bad_request"), (401, "authentication"), (404, "not_found"),
    (413, "payload_too_large"), (415, "unsupported_media_type"), (422, "validation"),
    (429, "rate_limited"), (529, "overloaded"), (500, "server_error"), (403, "http_error"), (302, "redirect")])
async def test_http_errors_are_fixed_redacted_and_not_retried(status, reason):
    with server(status=status, raw=(KEY + STATE["page"]).encode(), headers={"Location": "/v1/redirected"}) as (url, records, _):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            result = await client.evaluate(state=STATE, questions=QUESTIONS)
            assert result["ok"] is False
            assert result["reason"] == reason
            assert result["http_status"] == status
            assert isinstance(result["error"], str)
            assert KEY not in json.dumps(result)
            assert STATE["page"] not in json.dumps(result)
            assert len(records) == 1
        finally:
            await client.aclose()


async def test_timeout_and_cancellation_are_not_retried_or_swallowed():
    with server(delay=0.3) as (url, records, seen):
        client = JevClient(api_key=KEY, base_url=url, timeout=0.03)
        try:
            assert (await client.evaluate(state=STATE, questions=QUESTIONS))["reason"] == "timeout"
            assert len(records) == 1
        finally:
            await client.aclose()
    with server(delay=0.3) as (url, records, seen):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            task = asyncio.create_task(client.evaluate(state=STATE, questions=QUESTIONS))
            assert await asyncio.to_thread(seen.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert len(records) == 1
        finally:
            await client.aclose()


async def test_timeout_is_total_even_if_server_keeps_sending_chunks():
    with server(chunk_delay=0.01) as (url, records, _):
        client = JevClient(api_key=KEY, base_url=url, timeout=0.03)
        try:
            result = await client.evaluate(state=STATE, questions=QUESTIONS)
            assert result["reason"] == "timeout"
            assert len(records) == 1
        finally:
            await client.aclose()


async def test_structured_legend_cannot_replace_numbers_with_booleans():
    questions = deepcopy(QUESTIONS)
    questions["rating"]["criteria"] = [{"count": 1}, {"count": 2}]
    response = deepcopy(RESPONSE)
    response["answers"]["rating"]["legend"] = {"0": {"count": True}, "1": {"count": 2}}
    with server(body=response) as (url, _, _):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            result = await client.evaluate(state=STATE, questions=questions)
            assert result["reason"] == "invalid_response"
        finally:
            await client.aclose()


async def test_budget_edges_preserve_values_and_maximum_question_shapes():
    questions = {
        **{f"n{i}": {"type": "noul", "instructions": "Is it?"} for i in range(10)},
        "choice": {"type": "choice", "instructions": "Which?", "criteria": {f"c{i}": "Option" for i in range(32)}},
        "score": {"type": "score", "instructions": "How much?", "criteria": [f"Level {i}" for i in range(10)]},
    }
    answers = {f"n{i}": {"type": "noul", "noul": 0} for i in range(10)}
    answers["choice"] = {"type": "choice", "choice": "c0", "confidence": 1,
        "probabilities": {f"c{i}": int(i == 0) for i in range(32)}}
    answers["score"] = {"type": "score", "score": 9, "confidence": 1,
        "probabilities": {str(i): int(i == 9) for i in range(10)},
        "legend": {str(i): f"Level {i}" for i in range(10)}}
    response = {"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 0, "output_tokens": 0}}
    with server(body=response) as (url, records, _):
        client = JevClient(api_key=KEY, base_url=url.removesuffix("/v1"))
        try:
            state = " " + "中" * 47_996 + " "  # Exactly 48,000 serialized characters.
            result = await client.evaluate(state=state, questions=questions)
            assert result["ok"] is True
            assert records[0]["path"] == "/v1/systemone"
            assert records[0]["body"]["state"] == state
            assert (await client.evaluate(state=state + "x", questions=questions))["reason"] == "invalid_input"
            assert len(records) == 1
        finally:
            await client.aclose()


async def test_response_body_limit_is_bounded():
    response = deepcopy(RESPONSE)
    response["ignored"] = "x" * 512_001
    with server(body=response) as (url, _, _):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            assert (await client.evaluate(state=STATE, questions=QUESTIONS))["reason"] == "invalid_response"
        finally:
            await client.aclose()


async def test_distribution_rounding_tolerance_is_not_renormalized():
    response = deepcopy(RESPONSE)
    response["answers"]["route"]["probabilities"] = {"support": 0.8004, "other": 0.2}
    response["answers"]["rating"]["score"] = 0.7504
    with server(body=response) as (url, _, _):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            result = await client.evaluate(state=STATE, questions=QUESTIONS)
            assert result["ok"] is True
            assert result["answers"] == response["answers"]
        finally:
            await client.aclose()


@pytest.mark.parametrize("timeout", ["nan", "inf", "0", "-1", "61", "not-a-number"])
def test_invalid_environment_timeout_is_redacted(monkeypatch, timeout):
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)
    monkeypatch.setenv("TYPESAFE_TIMEOUT_SECONDS", timeout)
    with pytest.raises(ValueError) as caught:
        JevClient.from_env()
    assert str(caught.value) == "Invalid Jev configuration."


async def test_connection_error_is_redacted():
    with server() as (url, _, _):
        pass
    client = JevClient(api_key=KEY, base_url=url, timeout=0.5)
    try:
        result = await client.evaluate(state=STATE, questions=QUESTIONS)
        assert result["reason"] == "transport_error"
        assert KEY not in json.dumps(result)
        assert "127.0.0.1" not in json.dumps(result)
    finally:
        await client.aclose()
