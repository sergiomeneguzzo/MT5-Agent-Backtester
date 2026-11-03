import json

from mt5agent import Tester
from mt5agent.inputs import parse_inputs
from mt5agent.mcp import Server


def _server(client):
    return Server(lambda: Tester(client))


def rpc(server, method, params=None, mid=1):
    return server.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})


def test_initialize_and_list(client):
    s = _server(client)
    init = rpc(s, "initialize")["result"]
    assert init["serverInfo"]["name"] == "mt5-agent-backtester"
    names = [t["name"] for t in rpc(s, "tools/list")["result"]["tools"]]
    assert names == ["list_experts", "expert_inputs", "run_backtest", "run_optimization", "run_walk_forward",
                     "get_job", "list_jobs", "cancel_job"]
    assert not any(n.startswith("trade") for n in names)


def test_notifications_get_no_reply(client):
    assert _server(client).handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_run_backtest_tool(client, fake, sample_xlsx):
    fake.report_bytes = sample_xlsx
    reply = rpc(_server(client), "tools/call", {"name": "run_backtest", "arguments": {
        "expert": "X", "symbol": "EURUSD", "timeframe": "H1", "start": "2020-01-01", "end": "2021-12-31"}})
    data = json.loads(reply["result"]["content"][0]["text"])
    assert reply["result"]["isError"] is False
    assert data["profit_factor"] == 0.8815
    assert set(data["yearly_return_pct"]) == {"2020", "2021"}


def test_tool_errors_are_returned_to_agent(client):
    reply = rpc(_server(client), "tools/call", {"name": "run_optimization", "arguments": {
        "expert": "X", "symbol": "EURUSD", "timeframe": "H1", "start": "2020-01-01",
        "end": "2021-01-01", "inputs": {"P": 5}}})
    assert reply["result"]["isError"] is True
    assert "Range" in reply["result"]["content"][0]["text"]


def test_unknown_method(client):
    assert rpc(_server(client), "resources/list")["error"]["code"] == -32601


def test_parse_inputs_shapes():
    p = parse_inputs({"A": [1, 5, 1], "B": {"start": 0, "stop": 1, "step": 0.5}, "C": 3})
    assert p["A"].stop == 5 and p["B"].step == 0.5 and p["C"] == 3


def _call(server, name, arguments, mid=1, meta=None):
    params = {"name": name, "arguments": arguments}
    if meta:
        params["_meta"] = meta
    reply = rpc(server, "tools/call", params, mid)
    return reply["result"]["isError"], json.loads(reply["result"]["content"][0]["text"])


RUN = {"expert": "X", "symbol": "EURUSD", "timeframe": "H1", "start": "2020-01-01", "end": "2021-12-31"}


def test_long_tools_accept_background_flag(client):
    specs = {t["name"]: t for t in rpc(_server(client), "tools/list")["result"]["tools"]}
    for name in ("run_backtest", "run_optimization", "run_walk_forward"):
        assert "background" in specs[name]["inputSchema"]["properties"]
    assert "background" not in specs["list_experts"]["inputSchema"]["properties"]


def test_background_backtest_returns_a_job_and_finishes(client, fake, sample_xlsx):
    fake.report_bytes = sample_xlsx
    server = _server(client)
    error, started = _call(server, "run_backtest", {**RUN, "background": True})
    assert not error and started["status"] in ("queued", "running", "done")
    server.jobs.get(started["job_id"]).future.result(timeout=5)
    error, job = _call(server, "get_job", {"job_id": started["job_id"]})
    assert job["status"] == "done" and job["result"]["profit_factor"] == 0.8815
    _, jobs = _call(server, "list_jobs", {})
    assert jobs[0]["job_id"] == started["job_id"] and "result" not in jobs[0]


def test_failed_background_job_reports_the_error(client):
    server = _server(client)
    _, started = _call(server, "run_optimization", {**RUN, "inputs": {"P": 5}, "background": True})
    job = server.jobs.get(started["job_id"])
    try:
        job.future.result(timeout=5)
    except ValueError:
        pass
    _, view = _call(server, "get_job", {"job_id": started["job_id"]})
    assert view["status"] == "failed" and "Range" in view["error"]


def test_unknown_job_is_an_agent_visible_error(client):
    reply = rpc(_server(client), "tools/call", {"name": "get_job", "arguments": {"job_id": "nope"}})
    assert reply["result"]["isError"] is True


def test_progress_notifications_during_a_long_call(client):
    import io
    import threading

    from mt5agent.mcp import TOOLS, tool
    from mt5agent.mcp.tools import schema

    release = threading.Event()

    @tool("slow", "Slow tool for tests.", schema())
    def slow(ctx, args):
        ctx.progress("halfway")
        release.wait(5)
        return {"ok": True}

    try:
        server = Server(lambda: Tester(client), heartbeat=0.05)
        message = {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                   "params": {"name": "slow", "arguments": {}, "_meta": {"progressToken": "t1"}}}
        stdout = io.StringIO()
        threading.Timer(0.3, release.set).start()
        server.serve(io.StringIO(json.dumps(message) + "\n"), stdout)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        progress = [m for m in lines if m.get("method") == "notifications/progress"]
        assert progress and progress[0]["params"]["progressToken"] == "t1"
        assert "halfway" in progress[0]["params"]["message"]
        assert [m["params"]["progress"] for m in progress] == list(range(1, len(progress) + 1))
        assert lines[-1]["id"] == 7 and json.loads(lines[-1]["result"]["content"][0]["text"]) == {"ok": True}
    finally:
        TOOLS.pop("slow")


def test_queued_job_can_be_cancelled(client):
    import threading

    from mt5agent.mcp import TOOLS, tool
    from mt5agent.mcp.tools import schema

    gate = threading.Event()

    @tool("block", "Blocks the worker.", schema(), long_running=True)
    def block(ctx, args):
        gate.wait(5)
        return {}

    try:
        server = _server(client)
        _, first = _call(server, "block", {"background": True})
        _, second = _call(server, "block", {"background": True})
        _, cancelled = _call(server, "cancel_job", {"job_id": second["job_id"]})
        gate.set()
        assert cancelled["cancelled"] is True
        assert server.jobs.get(second["job_id"]).status == "cancelled"
    finally:
        TOOLS.pop("block")
