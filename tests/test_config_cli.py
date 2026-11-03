import io
import json

import pytest

from mt5agent.cli import build_parser, main
from mt5agent.config import TERMINAL_URL, Settings
from mt5agent.mcp import TOOLS, Server, tool
from mt5agent.mcp.tools import schema


def test_settings_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("MT5_MCP_KEY", raising=False)
    monkeypatch.delenv("MT5_MCP_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text("# comment\nMT5_MCP_KEY='abc123'\nMT5_MCP_TIMEOUT=60\n")
    s = Settings.from_env(dotenv=env)
    assert (s.url, s.key, s.timeout) == (TERMINAL_URL, "abc123", 60.0)
    assert "abc123" not in repr(s)


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("MT5_MCP_KEY=from-file\n")
    monkeypatch.setenv("MT5_MCP_KEY", "from-env")
    monkeypatch.setenv("MT5_MCP_URL", "http://127.0.0.1:9999/mcp")
    s = Settings.from_env(dotenv=env)
    assert s.key == "from-env" and s.url.endswith(":9999/mcp")


def test_missing_key_is_explained(tmp_path, monkeypatch):
    monkeypatch.delenv("MT5_MCP_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MT5_MCP_KEY"):
        Settings.from_env(dotenv=tmp_path / "missing.env")


def test_parser_has_every_command():
    sub = next(a for a in build_parser()._actions if a.dest == "command")
    assert set(sub.choices) == {"doctor", "tools", "experts", "inputs", "backtest", "optimize",
                                "walkforward", "report"}


def test_offline_report_command(tmp_path, sample_xlsx, optimization_xml, capsys):
    xlsx, xml = tmp_path / "r.xlsx", tmp_path / "o.xml"
    xlsx.write_bytes(sample_xlsx)
    xml.write_bytes(optimization_xml)
    assert main(["--json", "report", str(xlsx)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["trades"] == 2 and data["yearly_return_pct"]["2020"] == 1.98
    assert main(["--json", "report", str(xml)]) == 0
    assert json.loads(capsys.readouterr().out)["best"]["MovingPeriod"] == 80


def test_custom_tool_can_be_registered(client):
    @tool("count_experts", "How many experts are compiled.", schema())
    def count_experts(ctx, args):
        return {"count": 1}

    try:
        stdin = io.StringIO("\n".join(json.dumps(m) for m in (
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "count_experts"}},
            "not json",
        )) + "\n{broken\n")
        stdout = io.StringIO()
        Server(lambda: None).serve(stdin, stdout)
        replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
        by_id = {r["id"]: r for r in replies if r["id"] is not None}
        assert "count_experts" in [t["name"] for t in by_id[1]["result"]["tools"]]
        assert json.loads(by_id[2]["result"]["content"][0]["text"]) == {"count": 1}
        assert sorted(r["error"]["code"] for r in replies if r["id"] is None) == [-32700, -32600]
    finally:
        TOOLS.pop("count_experts")
