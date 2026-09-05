"""Remote MCP server connections for the chat agent.

Connects the harness tool loop to remote streamable-HTTP MCP servers
(e.g. Kaggle's MCP endpoint at ``https://www.kaggle.com/mcp``), discovering
their tools and exposing them alongside the local tools. Configured via
``THELAB_REMOTE_MCP_SERVERS`` (JSON: ``[{"name": ..., "url": ..., "headers":
{...}}]``) — network is only touched on explicit service start.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Cache file for the remote MCP server registry (tool inventory)
_REMOTE_CACHE_RELPATH = os.path.join(".thelab", "remote-mcp.json")

def remote_servers_config() -> list[dict[str, Any]]:
    """Parse THELAB_REMOTE_MCP_SERVERS env (JSON list) fail-soft."""
    raw = os.environ.get("THELAB_REMOTE_MCP_SERVERS", "")
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [entry for entry in parsed if isinstance(entry, dict) and entry.get("name") and entry.get("url")]


def _initialize_session(url: str, headers: dict[str, str]) -> dict[str, Any]:
    """Minimal JSON-RPC handshake with a streamable-HTTP MCP server."""
    import httpx

    session_headers = {
        **headers,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    with httpx.Client(timeout=30.0) as client:
        init_response = client.post(
            url,
            headers=session_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "thelab", "version": "1.0"},
                },
            },
        )
        init_response.raise_for_status()
        session_id = init_response.headers.get("mcp-session-id")
        if session_id:
            session_headers["mcp-session-id"] = session_id
        client.post(
            url,
            headers=session_headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        tools_response = client.post(
            url,
            headers=session_headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools_response.raise_for_status()

    payload = _extract_jsonrpc_result(tools_response, url)
    return {"session_id": session_id, "tools": payload.get("tools", [])}


def _extract_jsonrpc_result(response: Any, url: str) -> dict[str, Any]:
    """Parse an HTTP or SSE JSON-RPC response body."""
    text = response.text.strip()
    if text.startswith("{"):
        body = json.loads(text)
    else:
        for line in text.splitlines():
            if line.startswith("data: ") and "result" in line:
                body = json.loads(line[6:])
                break
        else:
            raise ValueError(f"unexpected MCP response shape from {url}")
    if "error" in body:
        raise ValueError(f"MCP error from {url}: {body['error']}")
    result: dict[str, Any] = body.get("result", {})
    return result


def _call_remote_tool(
    url: str,
    headers: dict[str, str],
    session_id: str | None,
    tool: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Call a remote tool and return a Lab-style {"ok", "data"/"error"} payload."""
    import httpx

    session_headers = {
        **headers,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        session_headers["mcp-session-id"] = session_id
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            url,
            headers=session_headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            },
        )
        response.raise_for_status()
    body = _extract_jsonrpc_result(response, url)
    content = body.get("content") or []
    text = "\n".join(
        str(item.get("text", "")) for item in content if isinstance(item, dict)
    )
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    return {"ok": body.get("isError") is not True, "data": parsed if parsed is not None else text}


async def call_remote_tool(server: dict[str, Any], tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Async wrapper around _call_remote_tool for the chat tool loop."""
    import asyncio

    return await asyncio.to_thread(
        _call_remote_tool,
        str(server["url"]),
        dict(server.get("headers") or {}),
        server.get("session_id"),
        tool,
        arguments,
    )


def discover_remote_tools() -> dict[str, Any]:
    """Probe all configured remote MCP servers.

    Returns a fail-soft registry: ``{"server_name": {"url", "reachable",
    "tools": [...], "error"?}}`` plus a flat ``"tools"`` map of
    ``server__tool`` -> connection info, and a ``"descriptions"`` map for the
    prompt/spec layer.
    """
    registry: dict[str, Any] = {"servers": {}, "tools": {}}
    for server in remote_servers_config():
        name = str(server["name"])
        url = str(server["url"])
        headers = dict(server.get("headers") or {})
        try:
            session = _initialize_session(url, headers)
            tools = []
            for tool in session.get("tools", []):
                tool_name = str(tool.get("name", ""))
                if not tool_name:
                    continue
                tools.append(
                    {
                        "name": tool_name,
                        "description": str(tool.get("description", "")),
                        "input_schema": tool.get("inputSchema") or {},
                        "remote": name,
                    }
                )
            registry["servers"][name] = {
                "url": url,
                "reachable": True,
                "tools": tools,
                "session_id": session.get("session_id"),
                "headers": headers,
            }
        except Exception as exc:  # noqa: BLE001 - probing must never break startup
            registry["servers"][name] = {
                "url": url,
                "reachable": False,
                "tools": [],
                "error": str(exc),
            }
    flat: dict[str, dict[str, Any]] = {}
    for server_name, info in registry["servers"].items():
        for tool in info.get("tools", []):
            flat[f"{server_name}__{tool['name']}"] = tool
    registry["tools"] = flat
    return registry


def _registry_cache_path() -> Path:
    return Path(os.environ.get("THELAB_WORKSPACE_ROOT", ".")) / _REMOTE_CACHE_RELPATH


def save_registry_cache(registry: dict[str, Any]) -> None:
    path = _registry_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, default=str), encoding="utf-8")


def load_registry_cache() -> dict[str, Any] | None:
    path = _registry_cache_path()
    if not path.is_file():
        return None
    try:
        data: dict[str, Any] | None = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data
