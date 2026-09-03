"""Agent harness: connect an LLM provider to the read-only MCP servers."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import ClientSession

from thelab.agents.grounding import extract_run_ids, metric_mismatches
from thelab.mcp.common import get_runs_root

from .provider import AgentMessage, LLMProvider, ToolCallRequest, ToolSpec


class GroundingError(Exception):
    """Raised when a provider's final answer is not grounded in workspace evidence."""

    def __init__(self, message: str, run_id: str | None = None):
        super().__init__(message)
        self.message = message
        self.run_id = run_id


class ApprovalRequiredError(Exception):
    """Raised when the provider requests a tool outside the read-only allowlist."""

    def __init__(self, request_path: Path, tool: str, arguments: dict[str, Any]):
        super().__init__(f"approval required for tool '{tool}'; request persisted at {request_path}")
        self.request_path = request_path
        self.tool = tool
        self.arguments = arguments


@dataclass
class ServerConnection:
    """Named connection to an MCP server session."""

    name: str
    session: ClientSession


class AgentHarness:
    """Run a bounded provider loop against the four read-only MCP servers."""

    def __init__(
        self,
        provider: LLMProvider,
        servers: list[ServerConnection],
        runs_root: Path | str | None = None,
        max_steps: int = 8,
        session_id: str | None = None,
        system_prompt: str | None = None,
    ) -> None:
        if not servers:
            raise ValueError("at least one MCP server connection is required")
        self.provider = provider
        self.servers = servers
        self.runs_root = Path(runs_root) if runs_root else Path(get_runs_root())
        self.max_steps = max(1, max_steps)
        self.session_id = session_id or f"sess-{uuid.uuid4().hex[:8]}"
        self.system_prompt = system_prompt or (
            "You are a grounded assistant for The Lab. "
            "Use only the provided read-only tools. "
            "Cite run_ids and metrics only when you can verify them."
        )
        self._tools: list[ToolSpec] = []
        self._allowlist: set[str] = set()
        self._tool_to_session: dict[str, ClientSession] = {}

    async def _discover_tools(self) -> None:
        """List tools from every connected server and pin the allowlist."""
        tools: list[ToolSpec] = []
        allowlist: set[str] = set()
        mapping: dict[str, ClientSession] = {}
        for conn in self.servers:
            result = await conn.session.list_tools()
            for tool in result.tools:
                allowlist.add(tool.name)
                mapping[tool.name] = conn.session
                tools.append(
                    ToolSpec(
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.input_schema if isinstance(tool.input_schema, dict) else {},
                    )
                )
        self._tools = tools
        self._allowlist = allowlist
        self._tool_to_session = mapping

    async def _call_tool(self, request: ToolCallRequest) -> dict[str, Any]:
        """Execute a single tool call and return the JSON payload."""
        session = self._tool_to_session.get(request.tool)
        if session is None:
            return {"ok": False, "error": f"tool '{request.tool}' is not available"}
        raw = await session.call_tool(request.tool, request.arguments)
        text = "".join(c.text for c in raw.content if hasattr(c, "text"))
        try:
            return json.loads(text) if text else {"ok": True, "data": None}
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"non-JSON tool response: {exc}"}

    def _workspace_session(self) -> ClientSession | None:
        """Return the workspace server session, if connected."""
        for conn in self.servers:
            if conn.name == "workspace":
                return conn.session
        return None

    async def _run_manifest(self, run_id: str) -> dict[str, Any] | None:
        """Fetch a run manifest via workspace_mcp.get_run_manifest."""
        session = self._workspace_session()
        if session is None:
            return None
        raw = await session.call_tool("get_run_manifest", {"run_id": run_id})
        text = "".join(c.text for c in raw.content if hasattr(c, "text"))
        try:
            payload = json.loads(text)
            return payload.get("data") if payload.get("ok") else None
        except json.JSONDecodeError:
            return None

    async def _run_metrics(self, run_id: str) -> dict[str, Any] | None:
        """Fetch metrics.json via workspace_mcp.get_artifact."""
        session = self._workspace_session()
        if session is None:
            return None
        raw = await session.call_tool("get_artifact", {"run_id": run_id, "artifact_type": "metrics"})
        text = "".join(c.text for c in raw.content if hasattr(c, "text"))
        try:
            payload = json.loads(text)
            return payload.get("data") if payload.get("ok") else None
        except json.JSONDecodeError:
            return None

    async def _check_grounding(self, text: str) -> None:
        """Verify every cited run_id exists and every metric claim matches evidence."""
        run_ids = extract_run_ids(text)
        if not run_ids:
            return

        for run_id in run_ids:
            manifest = await self._run_manifest(run_id)
            if manifest is None:
                raise GroundingError(
                    f"cited run_id '{run_id}' does not exist or is not readable", run_id=run_id
                )
            metrics = await self._run_metrics(run_id)
            if metrics is None:
                continue
            for key, (claimed, actual) in metric_mismatches(text, metrics).items():
                raise GroundingError(
                    f"metric claim {key}={claimed} for run {run_id} "
                    f"does not match evidence ({actual})",
                    run_id=run_id,
                )

    def _persist_approval_request(self, tool: str, arguments: dict[str, Any]) -> Path:
        """Persist a disallowed tool request under .thelab/approvals/."""
        approvals_dir = Path(".thelab") / "approvals"
        approvals_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).isoformat()
        filename = f"{self.session_id}_{timestamp.replace(':', '_')}.json"
        path = approvals_dir / filename
        payload = {
            "session_id": self.session_id,
            "tool": tool,
            "arguments": arguments,
            "timestamp": timestamp,
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    async def run(self, goal: str) -> dict[str, Any]:
        """Run the bounded agent loop for *goal* and return the outcome."""
        await self._discover_tools()

        messages: list[AgentMessage] = [
            AgentMessage(role="system", content=self.system_prompt),
            AgentMessage(role="user", content=goal),
        ]

        for _step in range(self.max_steps):
            turn = self.provider.complete(messages, self._tools)

            if turn.text is not None:
                try:
                    await self._check_grounding(turn.text)
                except GroundingError as exc:
                    return {
                        "status": "refused",
                        "reason": "grounding_failure",
                        "message": exc.message,
                        "run_id": exc.run_id,
                        "session_id": self.session_id,
                    }
                return {
                    "status": "success",
                    "answer": turn.text,
                    "session_id": self.session_id,
                }

            disallowed = [t for t in turn.tool_calls if t.tool not in self._allowlist]
            if disallowed:
                req = disallowed[0]
                path = self._persist_approval_request(req.tool, req.arguments)
                raise ApprovalRequiredError(path, req.tool, req.arguments)

            for request in turn.tool_calls:
                result = await self._call_tool(request)
                messages.append(
                    AgentMessage(
                        role="tool",
                        content=json.dumps(result, default=str),
                        tool_call_id=request.id or f"{request.tool}-{uuid.uuid4().hex[:4]}",
                    )
                )

        return {
            "status": "refused",
            "reason": "max_steps_exceeded",
            "message": f"agent loop exceeded max_steps ({self.max_steps})",
            "session_id": self.session_id,
        }
