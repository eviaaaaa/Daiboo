"""Executable HTTP contracts for the locked OpenAI SDK/LangChain adapter.

All endpoints bind loopback and use an inert API key: no provider consumption.
"""
import copy
import json
import os
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from langchain_core.messages import HumanMessage, ToolMessage, message_chunk_to_message

from utils.qwen_model import create_openai_compatible_model, normalize_content


@pytest.fixture
def endpoint(monkeypatch):
    replies = deque()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            if not replies:
                self.send_error(500, "No contract response queued")
                return
            content_type, payload, status = replies.popleft()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    # Keep tests independent of the developer's real provider configuration.
    for key in list(os.environ):
        if key.startswith("OPENAI_") or key == "LC_OUTPUT_VERSION":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "local-contract-key")
    monkeypatch.setenv("OPENAI_MODEL", "explicit-provider-model")
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")

    class Endpoint:
        def __init__(self):
            self.requests = requests

        def json(self, payload, status=200):
            replies.append(("application/json", json.dumps(payload).encode(), status))

        def sse(self, events, chat=False):
            frames = []
            for event in events:
                if not chat:
                    frames.append(f"event: {event['type']}\n")
                frames.append(f"data: {json.dumps(event)}\n\n")
            if chat:
                frames.append("data: [DONE]\n\n")
            replies.append(("text/event-stream", "".join(frames).encode(), 200))

    result = Endpoint()

    yield result
    server.shutdown()
    server.server_close()
    worker.join(timeout=5)
    assert not replies, "A queued request was never made"


def response(output, *, status="completed", response_id="resp_contract"):
    return {
        "id": response_id,
        "object": "response",
        "created_at": 1,
        "model": "explicit-provider-model",
        "status": status,
        "error": None,
        "incomplete_details": None,
        "output": output,
        "parallel_tool_calls": True,
        "tools": [],
        "tool_choice": "auto",
        "usage": {
            "input_tokens": 7,
            "output_tokens": 5,
            "total_tokens": 12,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 2},
        },
    }


def text_item(text="contract ok"):
    return {
        "type": "message", "id": "msg_contract", "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def reasoning_item(encrypted=True):
    result = {
        "type": "reasoning", "id": "rs_contract",
        "summary": [{"type": "summary_text", "text": "Checked the page."}],
    }
    if encrypted:
        result["encrypted_content"] = "opaque-provider-replay-token"
    return result


def function_item(arguments='{"query":"docs"}'):
    return {
        "type": "function_call", "id": "fc_contract", "call_id": "call_contract",
        "name": "lookup", "arguments": arguments, "status": "completed",
    }


TOOL = {
    "type": "function",
    "function": {
        "name": "lookup", "description": "Look up a page",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"]},
    },
}
IMAGE = "data:image/png;base64,aGVsbG8="


def test_responses_http_options_multimodal_and_replay(endpoint, monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "high")
    monkeypatch.setenv("OPENAI_REASONING_SUMMARY", "auto")
    monkeypatch.setenv("OPENAI_VERBOSITY", "low")
    monkeypatch.setenv("OPENAI_SERVICE_TIER", "default")
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "321")
    endpoint.json(response([reasoning_item(), function_item()]))
    endpoint.json(response([text_item()]))
    model = create_openai_compatible_model(max_retries=0, store=False)
    bound = model.bind_tools([TOOL])
    human = HumanMessage(content=[
        {"type": "text", "text": "Read this page"},
        {"type": "image_url", "image_url": {"url": IMAGE, "detail": "low"}},
    ])
    first = bound.invoke([human])
    assert first.tool_calls == [{"name": "lookup", "args": {"query": "docs"},
                                 "id": "call_contract", "type": "tool_call"}]
    assert first.content[0]["encrypted_content"] == "opaque-provider-replay-token"
    snapshot = copy.deepcopy(first.model_dump())
    assert normalize_content(first.content) == ""
    assert first.model_dump() == snapshot  # text display must not rewrite history
    final = bound.invoke([human, first, ToolMessage("page text", tool_call_id="call_contract")])
    assert normalize_content(final.content) == "contract ok"
    assert final.usage_metadata["total_tokens"] == 12
    path, payload = endpoint.requests[0]
    assert path == "/v1/responses"
    assert payload["model"] == "explicit-provider-model"
    assert payload["store"] is False
    assert payload["reasoning"] == {"effort": "high", "summary": "auto"}
    assert payload["text"]["verbosity"] == "low"
    assert payload["service_tier"] == "default"
    assert payload["max_output_tokens"] == 321
    assert "temperature" not in payload
    assert "reasoning.encrypted_content" in payload["include"]
    assert payload["tools"][0]["name"] == "lookup"
    assert payload["input"][0]["content"][1] == {
        "type": "input_image", "image_url": IMAGE, "detail": "low",
    }
    replay = endpoint.requests[1][1]
    assert "previous_response_id" not in replay  # full local history, no implicit server state
    assert next(i for i in replay["input"] if i["type"] == "reasoning") == reasoning_item()
    assert next(i for i in replay["input"] if i["type"] == "function_call")["call_id"] == "call_contract"
    assert next(i for i in replay["input"] if i["type"] == "function_call_output") == {
        "type": "function_call_output", "call_id": "call_contract", "output": "page text",
    }


def streaming_events():
    reasoning = reasoning_item(encrypted=False)
    func = function_item()
    message = text_item("All done")
    events = [
        {"type": "response.created", "response": response([], status="in_progress")},
        {"type": "response.output_item.added", "output_index": 0,
         "item": {"type": "reasoning", "id": "rs_contract", "summary": []}},
        {"type": "response.reasoning_summary_part.added", "output_index": 0,
         "item_id": "rs_contract", "summary_index": 0,
         "part": {"type": "summary_text", "text": ""}},
        {"type": "response.reasoning_summary_text.delta", "output_index": 0,
         "item_id": "rs_contract", "summary_index": 0, "delta": "Checked the page."},
        {"type": "response.output_item.done", "output_index": 0, "item": reasoning},
        {"type": "response.output_item.added", "output_index": 1,
         "item": {**func, "arguments": "", "status": "in_progress"}},
        {"type": "response.function_call_arguments.delta", "output_index": 1,
         "item_id": "fc_contract", "delta": '{"query":'},
        {"type": "response.function_call_arguments.delta", "output_index": 1,
         "item_id": "fc_contract", "delta": '"docs"}'},
        {"type": "response.function_call_arguments.done", "output_index": 1,
         "item_id": "fc_contract", "arguments": func["arguments"]},
        {"type": "response.output_item.done", "output_index": 1, "item": func},
        {"type": "response.output_item.added", "output_index": 2,
         "item": {**message, "content": [], "status": "in_progress"}},
        {"type": "response.output_text.delta", "output_index": 2, "content_index": 0,
         "item_id": "msg_contract", "delta": "All "},
        {"type": "response.output_text.delta", "output_index": 2, "content_index": 0,
         "item_id": "msg_contract", "delta": "done"},
        {"type": "response.output_text.done", "output_index": 2, "content_index": 0,
         "item_id": "msg_contract", "text": "All done"},
        {"type": "response.output_item.done", "output_index": 2, "item": message},
        {"type": "response.completed", "response": response([reasoning, func, message])},
    ]
    for sequence, event in enumerate(events):
        event["sequence_number"] = sequence
    return events


@pytest.mark.asyncio
async def test_responses_async_sse_tool_reasoning_and_history(endpoint, monkeypatch):
    monkeypatch.setenv("OPENAI_USE_RESPONSES_API", "true")
    monkeypatch.setenv("OPENAI_STREAMING", "true")
    endpoint.sse(streaming_events())
    endpoint.sse(streaming_events())
    model = create_openai_compatible_model(max_retries=0).bind_tools([TOOL])
    chunks = [chunk async for chunk in model.astream("Read the docs")]
    assert "All " in [normalize_content(chunk.content) for chunk in chunks]
    merged = message_chunk_to_message(sum(chunks[1:], chunks[0]))
    assert normalize_content(merged.content) == "All done"
    assert merged.tool_calls[0]["args"] == {"query": "docs"}
    assert merged.usage_metadata["output_token_details"]["reasoning"] == 2
    reason = next(block for block in merged.content if block["type"] == "reasoning")
    assert reason["id"] == "rs_contract"
    assert reason["summary"][0]["text"] == "Checked the page."
    await model.ainvoke([
        HumanMessage("Read the docs"), merged,
        ToolMessage("page text", tool_call_id="call_contract"),
    ])
    assert all(path == "/v1/responses" and body["stream"] for path, body in endpoint.requests)
    replay = endpoint.requests[1][1]["input"]
    assert next(i for i in replay if i["type"] == "reasoning")["id"] == "rs_contract"
    assert next(i for i in replay if i["type"] == "function_call")["id"] == "fc_contract"
    assert next(i for i in replay if i["type"] == "function_call_output")["output"] == "page text"


def chat_response(message):
    return {
        "id": "chatcmpl_contract", "object": "chat.completion", "created": 1,
        "model": "explicit-provider-model", "choices": [
            {"index": 0, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
             "message": {"role": "assistant", **message}},
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


def test_chat_completions_http_tool_multimodal_history(endpoint, monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "chat_completions")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "42")
    tool_call = {"type": "function", "id": "call_contract",
                 "function": {"name": "lookup", "arguments": '{"query":"docs"}'}}
    endpoint.json(chat_response({"content": None, "tool_calls": [tool_call]}))
    endpoint.json(chat_response({"content": "Found it"}))
    model = create_openai_compatible_model(max_retries=0).bind_tools([TOOL])
    human = HumanMessage(content=[{"type": "text", "text": "Look"},
                                 {"type": "image_url", "image_url": {"url": IMAGE}}])
    first = model.invoke([human])
    last = model.invoke([human, first, ToolMessage("result", tool_call_id="call_contract")])
    assert last.content == "Found it"
    assert first.tool_calls[0]["args"] == {"query": "docs"}
    path, payload = endpoint.requests[0]
    assert path == "/v1/chat/completions"
    assert payload["reasoning_effort"] == "low"
    assert payload["max_completion_tokens"] == 42
    assert "reasoning" not in payload and "include" not in payload and "temperature" not in payload
    assert payload["messages"][0]["content"][1]["image_url"]["url"] == IMAGE
    replay_call = endpoint.requests[1][1]["messages"][1]["tool_calls"][0]
    assert replay_call["id"] == tool_call["id"]
    assert replay_call["function"]["name"] == "lookup"
    assert json.loads(replay_call["function"]["arguments"]) == {"query": "docs"}
    assert endpoint.requests[1][1]["messages"][2] == {
        "role": "tool", "tool_call_id": "call_contract", "content": "result",
    }


def test_chat_sync_sse(endpoint, monkeypatch):
    monkeypatch.setenv("OPENAI_STREAMING", "1")
    events = [
        {"id": "chatcmpl_contract", "object": "chat.completion.chunk", "created": 1,
         "model": "explicit-provider-model",
         "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        for delta, finish in [({"role": "assistant", "content": "Hello "}, None),
                              ({"content": "world"}, None), ({}, "stop")]
    ]
    endpoint.sse(events, chat=True)
    result = create_openai_compatible_model(max_retries=0).invoke("hello")
    assert result.content == "Hello world"
    assert endpoint.requests[0][0] == "/v1/chat/completions"
    assert endpoint.requests[0][1]["stream"] is True


def test_responses_provider_error_is_not_retried_as_chat(endpoint, monkeypatch):
    from openai import BadRequestError

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    endpoint.json({"error": {"message": "unsupported model", "type": "invalid_request_error"}}, status=400)
    with pytest.raises(BadRequestError, match="unsupported model"):
        create_openai_compatible_model(max_retries=0).invoke("hello")
    assert len(endpoint.requests) == 1
    assert endpoint.requests[0][0] == "/v1/responses"


def test_responses_sync_sse_preserves_function_ids_and_blocks(endpoint, monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_STREAMING", "true")
    endpoint.sse(streaming_events())
    result = create_openai_compatible_model(max_retries=0).bind_tools([TOOL]).invoke("Read docs")
    assert result.id == "resp_contract"
    assert result.tool_calls[0]["id"] == "call_contract"
    assert result.tool_calls[0]["args"] == {"query": "docs"}
    assert normalize_content(result.content) == "All done"
    function = next(block for block in result.content if block["type"] == "function_call")
    assert function["id"] == "fc_contract"
    assert function["arguments"] == '{"query":"docs"}'
    assert endpoint.requests[0][0] == "/v1/responses"


def test_chat_sse_fragmented_tool_call(endpoint, monkeypatch):
    monkeypatch.setenv("OPENAI_STREAMING", "true")
    parts = [
        {"role": "assistant", "tool_calls": [{"index": 0, "id": "call_contract", "type": "function",
                                                "function": {"name": "lookup", "arguments": ""}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": '{"query":'}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": '"docs"}'}}]},
        {},
    ]
    events = [
        {"id": "chatcmpl_contract", "object": "chat.completion.chunk", "created": 1,
         "model": "explicit-provider-model", "choices": [
             {"index": 0, "delta": part, "finish_reason": "tool_calls" if index == 3 else None},
         ]}
        for index, part in enumerate(parts)
    ]
    endpoint.sse(events, chat=True)
    result = create_openai_compatible_model(max_retries=0).bind_tools([TOOL]).invoke("Read docs")
    assert result.tool_calls == [{"name": "lookup", "args": {"query": "docs"},
                                  "id": "call_contract", "type": "tool_call"}]
    assert endpoint.requests[0][0] == "/v1/chat/completions"


def test_responses_multimodal_tool_output(endpoint, monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    endpoint.json(response([function_item()]))
    endpoint.json(response([text_item()]))
    model = create_openai_compatible_model(max_retries=0).bind_tools([TOOL])
    human = HumanMessage("Capture page")
    first = model.invoke([human])
    model.invoke([human, first, ToolMessage(content=[
        {"type": "text", "text": "Screenshot"},
        {"type": "image_url", "image_url": {"url": IMAGE}},
    ], tool_call_id="call_contract")])
    replay = endpoint.requests[1][1]["input"]
    output = next(item for item in replay if item["type"] == "function_call_output")
    assert output["call_id"] == "call_contract"
    assert output["output"] == [
        {"type": "input_text", "text": "Screenshot"},
        {"type": "input_image", "image_url": IMAGE},
    ]


def test_upstream_streaming_encrypted_reasoning_replay(endpoint, monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_STREAMING", "true")
    events = streaming_events()
    for event in events:
        if event["type"] == "response.output_item.done" and event["output_index"] == 0:
            event["item"] = reasoning_item()
        if event["type"] == "response.completed":
            event["response"]["output"][0] = reasoning_item()
    endpoint.sse(events)
    result = create_openai_compatible_model(max_retries=0, store=False).invoke("Read docs")
    reasoning = next(block for block in result.content if block["type"] == "reasoning")
    assert reasoning["encrypted_content"] == "opaque-provider-replay-token"
