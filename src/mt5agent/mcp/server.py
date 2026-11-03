from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable
from typing import IO

from .._version import __version__
from ..client import MT5Client
from ..tester import Tester
from .tools import TOOLS

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "ai-agent-backtester"
INSTRUCTIONS = "Backtest-only access to the MetaTrader 5 Strategy Tester. No trading tools are exposed."

INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603
PARSE_ERROR = -32700


class Server:
    def __init__(self, tester_factory: Callable[[], Tester] | None = None):
        self._tester_factory = tester_factory or (lambda: Tester(MT5Client.connect()))
        self._tester: Tester | None = None
        self.tools = TOOLS

    @property
    def tester(self) -> Tester:
        if self._tester is None:
            self._tester = self._tester_factory()
        return self._tester

    def handle(self, message: dict) -> dict | None:
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, "Invalid request")
        request_id = message.get("id")
        if request_id is None:
            return None
        handler = {
            "initialize": self._initialize,
            "ping": lambda _: {},
            "tools/list": lambda _: {"tools": [t.spec() for t in self.tools.values()]},
            "tools/call": self._call_tool,
        }.get(message.get("method"))
        if handler is None:
            return _error(request_id, METHOD_NOT_FOUND, f"Method not found: {message.get('method')}")
        try:
            return {"jsonrpc": "2.0", "id": request_id, "result": handler(message.get("params") or {})}
        except Exception as exc:
            return _error(request_id, INTERNAL_ERROR, str(exc))

    def _initialize(self, _: dict) -> dict:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "instructions": INSTRUCTIONS,
        }

    def _call_tool(self, params: dict) -> dict:
        tool = self.tools.get(params.get("name", ""))
        if tool is None:
            raise KeyError(f"Unknown tool {params.get('name')!r}")
        try:
            data = tool.handler(self.tester, params.get("arguments") or {})
        except Exception as exc:
            return {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True}
        return {"content": [{"type": "text", "text": json.dumps(data, default=str)}], "isError": False}

    def serve(self, stdin: IO[str] = sys.stdin, stdout: IO[str] = sys.stdout) -> None:
        for line in stdin:
            if not line.strip():
                continue
            try:
                reply = self.handle(json.loads(line))
            except json.JSONDecodeError:
                reply = _error(None, PARSE_ERROR, "Parse error")
            except Exception:
                traceback.print_exc(file=sys.stderr)
                continue
            if reply is not None:
                stdout.write(json.dumps(reply) + "\n")
                stdout.flush()


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
