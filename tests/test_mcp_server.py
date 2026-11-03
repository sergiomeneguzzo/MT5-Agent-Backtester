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
    assert init["serverInfo"]["name"] == "ai-agent-backtester"
    names = [t["name"] for t in rpc(s, "tools/list")["result"]["tools"]]
    assert names == ["list_experts", "expert_inputs", "run_backtest", "run_optimization", "run_walk_forward"]
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
