from __future__ import annotations

import json
import sys
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import TimeoutError as FutureTimeout
from typing import IO, Any

from .._version import __version__
from ..client import MT5Client
from ..tester import Tester
from .jobs import JobQueue
from .tools import TOOLS, ToolContext

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "mt5-agent-backtester"
INSTRUCTIONS = (
    "Backtest-only access to the MetaTrader 5 Strategy Tester. No trading tools are exposed. "
    "Long runs accept background=true: you get a job_id back immediately, then poll get_job."
)
HEARTBEAT_SECONDS = 10.0

INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603
PARSE_ERROR = -32700

Notify = Callable[[str], None]


class Server:
    def __init__(self, tester_factory: Callable[[], Tester] | None = None, heartbeat: float = HEARTBEAT_SECONDS):
        self._tester_factory = tester_factory or (lambda: Tester(MT5Client.connect()))
        self._tester: Tester | None = None
        self._tester_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self.heartbeat = heartbeat
        self.jobs = JobQueue()
        self.tools = TOOLS

    @property
    def tester(self) -> Tester:
        with self._tester_lock:
            if self._tester is None:
                self._tester = self._tester_factory()
            return self._tester

    def handle(self, message: Any, notify: Notify | None = None) -> dict | None:
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, "Invalid request")
        request_id = message.get("id")
        if request_id is None:
            return None
        params = message.get("params") or {}
        handlers = {
            "initialize": lambda: self._initialize(),
            "ping": lambda: {},
            "tools/list": lambda: {"tools": [t.spec() for t in self.tools.values()]},
            "tools/call": lambda: self._call_tool(params, notify),
        }
        handler = handlers.get(message.get("method"))
        if handler is None:
            return _error(request_id, METHOD_NOT_FOUND, f"Method not found: {message.get('method')}")
        try:
            return {"jsonrpc": "2.0", "id": request_id, "result": handler()}
        except Exception as exc:
            return _error(request_id, INTERNAL_ERROR, str(exc))

    def serve(self, stdin: IO[str] = sys.stdin, stdout: IO[str] = sys.stdout) -> None:
        workers: list[threading.Thread] = []
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._write(stdout, _error(None, PARSE_ERROR, "Parse error"))
                continue
            if isinstance(message, dict) and message.get("method") == "tools/call" and "id" in message:
                worker = threading.Thread(target=self._answer_call, args=(message, stdout), daemon=True)
                worker.start()
                workers.append(worker)
            else:
                self._write(stdout, self.handle(message))
        for worker in workers:
            worker.join()
        self.jobs.shutdown()

    def _answer_call(self, message: dict, stdout: IO[str]) -> None:
        try:
            token = ((message.get("params") or {}).get("_meta") or {}).get("progressToken")
            notify = self._progress_notifier(token, stdout) if token is not None else None
            self._write(stdout, self.handle(message, notify))
        except Exception:
            traceback.print_exc(file=sys.stderr)

    def _progress_notifier(self, token: Any, stdout: IO[str]) -> Notify:
        count = 0

        def notify(text: str) -> None:
            nonlocal count
            count += 1
            self._write(stdout, {"jsonrpc": "2.0", "method": "notifications/progress",
                                 "params": {"progressToken": token, "progress": count, "message": text}})
        return notify

    def _initialize(self) -> dict:
        return {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__}, "instructions": INSTRUCTIONS}

    def _call_tool(self, params: dict, notify: Notify | None) -> dict:
        tool = self.tools.get(params.get("name", ""))
        if tool is None:
            raise KeyError(f"Unknown tool {params.get('name')!r}")
        args = params.get("arguments") or {}
        try:
            if tool.inline:
                return _content(tool.handler(self._context(), args))
            job = self.jobs.submit(tool.name, lambda j: tool.handler(self._context(j), args))
            if tool.long_running and args.get("background"):
                return _content(job.view())
            return _content(self._wait(job, notify))
        except Exception as exc:
            return _content(f"{type(exc).__name__}: {exc}", error=True)

    def _context(self, job=None) -> ToolContext:
        return ToolContext(lambda: self.tester, self.jobs, job)

    def _wait(self, job, notify: Notify | None) -> Any:
        while True:
            try:
                return job.future.result(timeout=self.heartbeat)
            except FutureTimeout:
                if notify:
                    notify(f"{job.progress or job.status} ({job.elapsed():.0f}s)")

    def _write(self, stdout: IO[str], payload: dict | None) -> None:
        if payload is None:
            return
        with self._write_lock:
            stdout.write(json.dumps(payload, default=str) + "\n")
            stdout.flush()


def _content(data: Any, error: bool = False) -> dict:
    text = data if isinstance(data, str) else json.dumps(data, default=str)
    return {"content": [{"type": "text", "text": text}], "isError": error}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
