"""Bounded, text/JSON-only native TypeSafe System One client.

Jev supplies advisory judgments, never authorization or browser actions. This
client performs one HTTP request: no retries, redirects, model fallback, asset
uploads, image interpretation, or long-context opt-in. Call ``aclose`` from the
owning session's AsyncExitStack. Only the HTTP transport is created lazily.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from typing import Annotated, Any, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

MAX_STATE_CHARS = 48_000
MAX_QUESTIONS = 12
MAX_QUESTION_CHARS = 24_000
MAX_QUESTIONS_CHARS = 48_000
MAX_INSTRUCTIONS_CHARS = 8_000
MAX_DESCRIPTION_CHARS = 4_000
MAX_DEPTH = 16
MAX_RESPONSE_BYTES = 512_000
PROBABILITY_TOLERANCE = 1e-3
# The native service independently quantizes scores/probabilities to hundredths.
# Observed live: score=.19 with probabilities {.82,.18,0}, weighted=.18.
# Permit one hundredth plus float error, preserving both original wire values;
# this does NOT relax probability bounds, distributions or action thresholds.
SCORE_ROUNDING_TOLERANCE = 0.010000001

Description = Union[str, dict[str, Any], list[Any]]


def _json_text(value: Any, *, limit: int) -> str:
    """Check actual JSON types before serialization can coerce keys/tuples/NaNs."""
    stack = [(value, 0)]
    nodes = 0
    characters = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > 20_000:
            raise ValueError("JSON budget exceeded.")
        if type(item) in (dict, list):
            if depth >= MAX_DEPTH or len(item) > 20_000:
                raise ValueError("JSON nesting or item budget exceeded.")
            if type(item) is dict:
                if any(type(key) is not str for key in item):
                    raise ValueError("JSON keys must be strings.")
                # These are media protocol objects, not ordinary text/JSON state.
                media_type = item.get("type")
                if isinstance(media_type, str) and media_type.lower() in {
                    "asset", "image", "image_url", "input_image", "box",
                }:
                    raise ValueError("Media inputs are not supported.")
                characters += sum(len(key) for key in item)
                stack.extend((child, depth + 1) for child in item.values())
            else:
                stack.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            characters += len(item)
        elif type(item) in (int, float):
            try:
                finite = math.isfinite(item)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("JSON numbers must be finite.")
        elif item is not None and type(item) is not bool:
            raise ValueError("Unsupported JSON value.")
        if characters > limit:
            raise ValueError("JSON character budget exceeded.")
    result = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(result) > limit:
        raise ValueError("JSON character budget exceeded.")
    result.encode("utf-8")  # Reject lone surrogates before creating the transport.
    return result


def _description(value: Any, *, limit: int) -> Any:
    if type(value) not in (str, dict, list) or not value:
        raise ValueError("A nonempty text/JSON description is required.")
    if isinstance(value, str) and not value.strip():
        raise ValueError("A nonempty description is required.")
    _json_text(value, limit=limit)
    return value


def _identifier(value: Any) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= 128


class _Question(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")
    instructions: Description

    @field_validator("instructions", mode="before")
    @classmethod
    def _instructions(cls, value: Any) -> Any:
        return _description(value, limit=MAX_INSTRUCTIONS_CHARS)


class NoulQuestion(_Question):
    type: Literal["noul"] = "noul"
    criteria: dict[Literal["true", "false"], Description] | None = None

    @field_validator("criteria", mode="before")
    @classmethod
    def _criteria(cls, value: Any) -> Any:
        if value is None:
            return value
        if type(value) is not dict or not value or any(type(key) is not str or key not in {"true", "false"} for key in value):
            raise ValueError("Only true/false criteria are supported.")
        for description in value.values():
            _description(description, limit=MAX_DESCRIPTION_CHARS)
        return value


class ChoiceQuestion(_Question):
    type: Literal["choice"] = "choice"
    criteria: dict[str, Description]

    @field_validator("criteria", mode="before")
    @classmethod
    def _criteria(cls, value: Any) -> Any:
        if type(value) is not dict or not 2 <= len(value) <= 32 or not all(_identifier(key) for key in value):
            raise ValueError("Choice requires 2..32 nonempty string options.")
        for description in value.values():
            _description(description, limit=MAX_DESCRIPTION_CHARS)
        return value


class ScoreQuestion(_Question):
    type: Literal["score"] = "score"
    criteria: list[Description]

    @field_validator("criteria", mode="before")
    @classmethod
    def _criteria(cls, value: Any) -> Any:
        if type(value) is not list or not 2 <= len(value) <= 10:
            raise ValueError("Score requires 2..10 ordered levels.")
        for description in value:
            _description(description, limit=MAX_DESCRIPTION_CHARS)
        return value


JevQuestion = Annotated[Union[NoulQuestion, ChoiceQuestion, ScoreQuestion], Field(discriminator="type")]
_QUESTION_ADAPTER = TypeAdapter(JevQuestion)


def jev_enabled() -> bool:
    """Opt-in only; missing/unrecognized configuration remains disabled."""
    return os.getenv("DAIBOO_JEV_ENABLED", "false").lower() in {"true", "1"}


def _failure(reason: str, http_status: int | None = None) -> dict:
    messages = {
        "invalid_input": "Invalid Jev text/JSON input or request budget exceeded.",
        "invalid_response": "Jev returned an invalid response.",
        "timeout": "Jev request timed out.",
        "transport_error": "Jev request could not be completed.",
        "closed": "Jev client is closed.",
        "bad_request": "Jev rejected the request.",
        "authentication": "Jev authentication failed.",
        "not_found": "Jev endpoint or model was not found.",
        "payload_too_large": "Jev request is too large.",
        "unsupported_media_type": "Jev rejected the media type.",
        "validation": "Jev request validation failed.",
        "rate_limited": "Jev rate limit reached.",
        "overloaded": "Jev is temporarily overloaded.",
        "redirect": "Jev redirects are not permitted.",
        "server_error": "Jev service failed.",
        "http_error": "Jev returned an HTTP error.",
    }
    result = {"ok": False, "reason": reason, "error": messages[reason]}
    if http_status is not None:
        result["http_status"] = http_status
    return result


def _probability(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def _distribution(value: Any, keys: set[str]) -> dict:
    if type(value) is not dict or set(value) != keys or not all(_probability(p) for p in value.values()):
        raise ValueError("Invalid distribution.")
    if not math.isclose(math.fsum(value.values()), 1, rel_tol=0, abs_tol=PROBABILITY_TOLERANCE):
        raise ValueError("Invalid distribution total.")
    return value


def _response(body: Any, questions: dict[str, dict]) -> dict:
    if type(body) is not dict or not _identifier(body.get("model")):
        raise ValueError("Invalid response model.")
    answers = body.get("answers")
    if type(answers) is not dict or set(answers) != set(questions):
        raise ValueError("Invalid answer ids.")
    safe_answers = {}
    for question_id, question in questions.items():
        answer = answers[question_id]
        kind = question["type"]
        if type(answer) is not dict or answer.get("type") != kind:
            raise ValueError("Invalid answer type.")
        safe = {"type": kind}
        if kind == "noul":
            if not _probability(answer.get("noul")):
                raise ValueError("Invalid noul.")
            safe["noul"] = answer["noul"]
        else:
            if not _probability(answer.get("confidence")):
                raise ValueError("Invalid confidence.")
            safe["confidence"] = answer["confidence"]
            if kind == "choice":
                probabilities = _distribution(answer.get("probabilities"), set(question["criteria"]))
                choice = answer.get("choice")
                if type(choice) is not str or choice not in probabilities:
                    raise ValueError("Invalid choice.")
                if probabilities[choice] < max(probabilities.values()) - 1e-9:
                    raise ValueError("Choice is not a highest-probability option.")
                safe["choice"] = choice
            else:
                criteria = question["criteria"]
                keys = {str(i) for i in range(len(criteria))}
                probabilities = _distribution(answer.get("probabilities"), keys)
                legend = answer.get("legend")
                expected_legend = {str(i): description for i, description in enumerate(criteria)}
                if not _same_json(legend, expected_legend):
                    raise ValueError("Invalid score legend.")
                score: Any = answer.get("score")
                if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= len(criteria) - 1:
                    raise ValueError("Invalid score.")
                weighted = math.fsum(i * probabilities[str(i)] for i in range(len(criteria)))
                if not math.isclose(score, weighted, rel_tol=0, abs_tol=SCORE_ROUNDING_TOLERANCE):
                    raise ValueError("Score does not match distribution.")
                safe.update(score=score, legend=legend)
            safe["probabilities"] = probabilities
        safe_answers[question_id] = safe
    usage = body.get("usage")
    if type(usage) is not dict or any(type(usage.get(key)) is not int or usage[key] < 0 for key in ("input_tokens", "output_tokens")):
        raise ValueError("Invalid usage.")
    return {
        "ok": True, "model": body["model"], "answers": safe_answers,
        "usage": {key: usage[key] for key in ("input_tokens", "output_tokens")},
    }


def _same_json(left: Any, right: Any) -> bool:
    """Structural equality without Python's accidental True == 1 equivalence."""
    if type(left) is dict and type(right) is dict:
        return set(left) == set(right) and all(_same_json(left[key], right[key]) for key in left)
    if type(left) is list and type(right) is list:
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    return type(left) is type(right) and left == right


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("Non-finite JSON number.")


class JevClient:
    """One session-owned, reusable httpx connection pool; credentials stay private."""

    def __init__(
        self, *, api_key: str, base_url: str = "https://api.typesafe.ai/v1",
        model: str = "jev-latest", timeout: float = 10,
    ) -> None:
        try:
            if type(api_key) is not str or not api_key or not api_key.isascii() or any(ord(c) <= 32 or ord(c) >= 127 for c in api_key):
                raise ValueError
            if type(model) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model) is None:
                raise ValueError
            if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
                raise ValueError
            if type(base_url) is not str or base_url != base_url.strip():
                raise ValueError
            parts = urlsplit(base_url)
            if parts.username is not None or parts.password is not None or parts.query or parts.fragment or "?" in base_url or "#" in base_url:
                raise ValueError
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.path not in {"", "/", "/v1", "/v1/"}:
                raise ValueError
            if parts.scheme == "http" and parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError
            if parts.port is not None and parts.port <= 0:
                raise ValueError
            if any(ord(c) <= 32 or ord(c) >= 127 for c in base_url) or "\\" in base_url:
                raise ValueError
            canonical = f"{parts.scheme}://{parts.netloc}/v1"
            httpx.URL(canonical)
        except (ValueError, TypeError, OverflowError, httpx.InvalidURL):
            raise ValueError("Invalid Jev configuration.") from None
        self._api_key = api_key
        self.base_url = canonical
        self.model = model
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._closed = False

    @classmethod
    def from_env(cls) -> JevClient:
        raw_timeout = os.getenv("TYPESAFE_TIMEOUT_SECONDS", "10")
        try:
            timeout = float(raw_timeout)
        except (ValueError, OverflowError):
            raise ValueError("Invalid Jev configuration.") from None
        return cls(
            api_key=os.getenv("TYPESAFE_API_KEY", ""),
            base_url=os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1"),
            model=os.getenv("TYPESAFE_MODEL", "jev-latest"), timeout=timeout,
        )

    async def evaluate(self, *, state: Any, questions: dict) -> dict:
        if self._closed:
            return _failure("closed")
        try:
            _description(state, limit=MAX_STATE_CHARS)
            if type(questions) is not dict or not 1 <= len(questions) <= MAX_QUESTIONS or not all(_identifier(key) for key in questions):
                raise ValueError("Invalid question map.")
            validated = {}
            for question_id, question in questions.items():
                # Dump then revalidate even model_construct/mutated models, including extras.
                if isinstance(question, _Question):
                    question = question.model_dump(exclude_none=True)
                value = _QUESTION_ADAPTER.validate_python(question).model_dump(exclude_none=True)
                _json_text(value, limit=MAX_QUESTION_CHARS)
                validated[question_id] = value
            _json_text(validated, limit=MAX_QUESTIONS_CHARS)
            payload = _json_text({"state": state, "model": self.model, "questions": validated}, limit=100_000).encode("utf-8")
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
            return _failure("invalid_input")
        started = time.monotonic()
        try:
            if self._client is None:
                # Keep httpx's normal trust_env behavior for the project's proxies.
                self._client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=False)
            async with asyncio.timeout(self.timeout):
                async with self._client.stream(
                    "POST", f"{self.base_url}/systemone", content=payload,
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                ) as response:
                    status = response.status_code
                    if status != 200:
                        reason = {
                            400: "bad_request", 401: "authentication", 404: "not_found",
                            413: "payload_too_large", 415: "unsupported_media_type",
                            422: "validation", 429: "rate_limited", 529: "overloaded",
                        }.get(status, "redirect" if 300 <= status < 400 else "server_error" if status >= 500 else "http_error")
                        return _failure(reason, status)
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_RESPONSE_BYTES:
                            return _failure("invalid_response")
            body = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            # Also bound untrusted response nesting before structured comparisons.
            _json_text(body, limit=MAX_RESPONSE_BYTES)
            result = _response(body, validated)
        except (httpx.TimeoutException, TimeoutError):
            return _failure("timeout")
        except (httpx.HTTPError, httpx.InvalidURL, OSError):
            return _failure("transport_error")
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
            return _failure("invalid_response")
        result["elapsed_seconds"] = time.monotonic() - started
        return result

    async def aclose(self) -> None:
        self._closed = True
        if self._client is not None:
            await self._client.aclose()
