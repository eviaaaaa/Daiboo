"""Request-local progressive disclosure of real browser tool schemas.

Wire before ContextManagerMiddleware so its wrap_model_call sees the selected
schemas rather than the full registry. Keep all tools registered with the agent
for ToolNode execution; only the model request is narrowed. No dispatcher, model
name capability inference, mutable per-agent grants, or fabricated schemas.

Discovery is replay-derived: completed successful browser_runtime_info calls in
the retained history unlock up to five exact names. After their entire turn is
archived, ask for those schemas again. This bounds disclosure without leaking
grants across threads sharing one agent instance.
"""
from __future__ import annotations

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage


CORE_BROWSER_TOOLS = frozenset({
    "browser_navigate", "browser_snapshot", "browser_tabs", "browser_batch",
    "browser_runtime_info", "web_observe",
    "browser_jev_decide", "browser_jev_run",  # Only present when explicitly enabled.
})


def _tool_name(tool) -> str:
    if isinstance(tool, dict):
        function = tool.get("function")
        return function.get("name", "") if isinstance(function, dict) else tool.get("name", "")
    return getattr(tool, "name", "")


def _disclosed_groups(messages) -> list[list[str]]:
    pending = {}
    disclosed = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if call.get("name") != "browser_runtime_info":
                    continue
                args = call.get("args", {})
                names = args.get("tool_names", []) if isinstance(args, dict) else []
                if (isinstance(names, list) and len(names) <= 5
                        and all(isinstance(name, str) for name in names)):
                    pending[call["id"]] = names
        elif isinstance(message, ToolMessage):
            names = pending.pop(message.tool_call_id, None)
            if names is not None and message.status == "success":
                disclosed.append(names)
    return disclosed


class BrowserDisclosureMiddleware(AgentMiddleware):
    """Narrow browser schemas; leave non-browser tools and ToolNode unchanged."""

    def _prepare_request(self, request):
        disclosed = _disclosed_groups(request.messages)
        resident, expanded = [], []
        deferred = []
        for tool in request.tools or []:
            name = _tool_name(tool)
            if name in CORE_BROWSER_TOOLS or not name.startswith("browser_"):
                resident.append(tool)
            else:
                deferred.append(tool)
        seen = set()
        # Keep prior discovery batches byte-order stable. Within each new batch,
        # use the registry order, and append only genuinely new native schemas.
        for names in disclosed:
            for tool in deferred:
                name = _tool_name(tool)
                if name in names and name not in seen:
                    expanded.append(tool)
                    seen.add(name)
        # Exact original tool objects/dicts are forwarded, not rebuilt schemas.
        selected = resident + expanded
        if selected == request.tools:
            return request
        return request.override(tools=selected)

    def wrap_model_call(self, request, handler):
        return handler(self._prepare_request(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._prepare_request(request))
