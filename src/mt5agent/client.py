"""Minimal, dependency-free client for the MCP servers built into MetaTrader 5.

MetaTrader 5 (build 6230+) ships two local MCP servers speaking JSON-RPC over
"streamable HTTP": the terminal (Strategy Tester, charts, journals, history) and
MetaEditor (compiler, files). This module talks to either one.

Safety first: the terminal server also exposes ``trade_*`` tools that send real
orders. The client refuses them unless you explicitly opt in with
``allow_trading=True``. Backtesting never needs them.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from .config import Settings

PROTOCOL_VERSION = "2025-06-18"

#: Tool-name prefixes that can touch a real account. Blocked by default.
TRADING_PREFIXES = ("trade_",)

#: Tools that change terminal state outside the tester (Market Watch, live charts).
STATEFUL_TOOLS = frozenset({
    "chart_add_expert", "chart_add_script", "chart_apply_template",
    "add_marketwatch_symbol", "remove_marketwatch_symbol",
})


class MT5Error(RuntimeError):
    """Raised for JSON-RPC errors and tool calls that report ``isError``."""


class TradingBlockedError(PermissionError):
    """Raised when a ``trade_*`` tool is called on a read-only client."""


Transport = Callable[[dict, dict], tuple[str, dict]]


def _http_transport(url: str, timeout: float) -> Transport:
    def send(body: dict, headers: dict) -> tuple[str, dict]:
        req = urllib.request.Request(url, json.dumps(body).encode(), headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace"), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise MT5Error(
                    "401 Unauthorized: wrong MCP key, or the key was regenerated and "
                    "MetaTrader 5 has not been restarted yet."
                ) from None
            raise MT5Error(f"HTTP {exc.code} from MetaTrader 5 MCP server") from None
        except urllib.error.URLError as exc:
            raise MT5Error(
                f"Cannot reach {url} ({exc.reason}). Is MetaTrader 5 open with the MCP "
                "server enabled (Tools > Options > MCP)?"
            ) from None
    return send


def _decode(payload: str) -> dict:
    """Accept both plain JSON and Server-Sent-Events framed responses."""
    text = payload.strip()
    if text.startswith("{"):
        return json.loads(text)
    data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    for chunk in reversed(data):
        if chunk.startswith("{"):
            return json.loads(chunk)
    raise MT5Error(f"Unexpected MCP response: {text[:200]!r}")


class MT5Client:
    """JSON-RPC session with one MetaTrader 5 MCP server.

    >>> mt5 = MT5Client.connect()               # reads MT5_MCP_URL / MT5_MCP_KEY
    >>> mt5.call("get_time_information")
    """

    def __init__(
        self,
        settings: Settings,
        *,
        allow_trading: bool = False,
        timeout: float = 3600,
        transport: Transport | None = None,
    ) -> None:
        self.settings = settings
        self.allow_trading = allow_trading
        self._send = transport or _http_transport(settings.url, timeout)
        self._session: str | None = None
        self._next_id = 0
        self.workspace: dict = {}
        self._handshake()

    @classmethod
    def connect(cls, editor: bool = False, **kwargs: Any) -> MT5Client:
        return cls(Settings.load(editor=editor), **kwargs)

    # -- protocol ---------------------------------------------------------
    def _headers(self) -> dict:
        h = {
            "Authorization": f"Bearer {self.settings.key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self._session:
            h["Mcp-Session-Id"] = self._session
        return h

    def _post(self, body: dict) -> str:
        text, headers = self._send(body, self._headers())
        lowered = {k.lower(): v for k, v in headers.items()}
        self._session = lowered.get("mcp-session-id") or self._session
        return text

    def _rpc(self, method: str, params: dict) -> Any:
        self._next_id += 1
        reply = _decode(self._post({"jsonrpc": "2.0", "id": self._next_id,
                                    "method": method, "params": params}))
        if "error" in reply:
            raise MT5Error(reply["error"])
        return reply.get("result")

    def _handshake(self) -> None:
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mt5-agent-backtester", "version": "0.1.0"},
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        # The MT5 servers require get_workspace_info as the first call of a session.
        self.workspace = self.call("get_workspace_info")

    # -- public API -------------------------------------------------------
    def tools(self) -> list[dict]:
        tools = self._rpc("tools/list", {})["tools"]
        if self.allow_trading:
            return tools
        return [t for t in tools if not t["name"].startswith(TRADING_PREFIXES)]

    def call(self, tool: str, arguments: dict | None = None) -> Any:
        if tool.startswith(TRADING_PREFIXES) and not self.allow_trading:
            raise TradingBlockedError(
                f"'{tool}' can place or modify real orders and is blocked. "
                "Create the client with allow_trading=True if you really mean it."
            )
        result = self._rpc("tools/call", {"name": tool, "arguments": arguments or {}})
        if result.get("structuredContent") is not None:
            out = result["structuredContent"]
        else:
            text = "".join(c.get("text", "") for c in result.get("content", []))
            try:
                out = json.loads(text)
            except ValueError:
                out = {"text": text}
        if result.get("isError"):
            raise MT5Error(f"{tool}: {out}")
        return out

    # -- workspace helpers ------------------------------------------------
    @property
    def mql5_folder(self) -> str:
        return self.workspace.get("workspace", {}).get("mql5_folder", r"C:\Program Files\MetaTrader 5\MQL5")

    def mql5_path(self, *parts: str) -> str:
        return "\\".join([self.mql5_folder.rstrip("\\"), *parts])

    def read_bytes(self, path: str) -> bytes:
        """Download a file under an allowed read root (e.g. a saved report)."""
        reply = self.call("read_binary_file", {"path": path})
        data = reply.get("data", "")
        if reply.get("encoding", "hex") != "hex":
            raise MT5Error(f"Unsupported encoding {reply.get('encoding')!r}")
        return bytes.fromhex(data)
