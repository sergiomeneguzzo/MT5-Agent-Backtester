from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from ._version import __version__
from .config import Settings
from .errors import MT5Error, TradingBlockedError

PROTOCOL_VERSION = "2025-06-18"
TRADING_PREFIXES = ("trade_",)
DEFAULT_MQL5_FOLDER = r"C:\Program Files\MetaTrader 5\MQL5"

Transport = Callable[[dict, dict], tuple[str, dict]]


def http_transport(url: str, timeout: float) -> Transport:
    def send(body: dict, headers: dict) -> tuple[str, dict]:
        request = urllib.request.Request(url, json.dumps(body).encode(), headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "replace"), dict(response.headers)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise MT5Error("401 Unauthorized: wrong key, or MT5 was not restarted after generating it") from None
            raise MT5Error(f"HTTP {exc.code} from {url}") from None
        except urllib.error.URLError as exc:
            raise MT5Error(f"Cannot reach {url} ({exc.reason}). Is MetaTrader 5 running with MCP enabled?") from None

    return send


class MT5Client:
    def __init__(self, settings: Settings, *, allow_trading: bool = False, transport: Transport | None = None):
        self.settings = settings
        self.allow_trading = allow_trading
        self._send = transport or http_transport(settings.url, settings.timeout)
        self._session_id: str | None = None
        self._request_id = 0
        self.workspace = self._handshake()

    @classmethod
    def connect(cls, editor: bool = False, **kwargs: Any) -> MT5Client:
        return cls(Settings.from_env(editor=editor), **kwargs)

    def call(self, tool: str, arguments: dict | None = None) -> Any:
        if tool.startswith(TRADING_PREFIXES) and not self.allow_trading:
            raise TradingBlockedError(f"'{tool}' can send real orders and is blocked (allow_trading=False)")
        result = self._rpc("tools/call", {"name": tool, "arguments": arguments or {}})
        payload = result.get("structuredContent")
        if payload is None:
            text = "".join(part.get("text", "") for part in result.get("content", []))
            try:
                payload = json.loads(text)
            except ValueError:
                payload = {"text": text}
        if result.get("isError"):
            raise MT5Error(f"{tool}: {payload}")
        return payload

    def tools(self) -> list[dict]:
        tools = self._rpc("tools/list", {})["tools"]
        return tools if self.allow_trading else [t for t in tools if not t["name"].startswith(TRADING_PREFIXES)]

    def read_bytes(self, path: str) -> bytes:
        reply = self.call("read_binary_file", {"path": path})
        if reply.get("encoding", "hex") != "hex":
            raise MT5Error(f"Unsupported encoding {reply.get('encoding')!r}")
        return bytes.fromhex(reply.get("data", ""))

    @property
    def mql5_folder(self) -> str:
        return self.workspace.get("workspace", {}).get("mql5_folder", DEFAULT_MQL5_FOLDER)

    def mql5_path(self, *parts: str) -> str:
        return "\\".join([self.mql5_folder.rstrip("\\"), *parts])

    def _handshake(self) -> dict:
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ai-agent-backtester", "version": __version__},
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self.call("get_workspace_info")

    def _rpc(self, method: str, params: dict) -> Any:
        self._request_id += 1
        reply = _decode(self._post({"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}))
        if "error" in reply:
            raise MT5Error(reply["error"])
        return reply.get("result")

    def _post(self, body: dict) -> str:
        headers = {
            "Authorization": f"Bearer {self.settings.key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        text, response_headers = self._send(body, headers)
        lowered = {k.lower(): v for k, v in response_headers.items()}
        self._session_id = lowered.get("mcp-session-id") or self._session_id
        return text


def _decode(payload: str) -> dict:
    text = payload.strip()
    if text.startswith("{"):
        return json.loads(text)
    events = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    for event in reversed(events):
        if event.startswith("{"):
            return json.loads(event)
    raise MT5Error(f"Unexpected MCP response: {text[:200]!r}")
