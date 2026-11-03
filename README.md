<p align="center">
  <img src="docs/images/banner.svg" alt="MT5-Agent-Backtester" width="100%">
</p>

<p align="center">
  <a href="https://github.com/sergiomeneguzzo/MT5-Agent-Backtester/actions/workflows/ci.yml"><img src="https://github.com/sergiomeneguzzo/MT5-Agent-Backtester/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/MetaTrader%205-build%206230%2B-1f6feb" alt="MetaTrader 5 build 6230+">
  <img src="https://img.shields.io/badge/dependencies-0-3fb950" alt="zero dependencies">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="MIT"></a>
</p>

**MT5-Agent-Backtester** lets you run backtests, optimizations and walk-forward analysis in the real
MetaTrader 5 Strategy Tester from Python, from the terminal or from an AI agent such as Claude Code or Cursor.

It talks to the MCP server that ships inside MetaTrader 5 (build 6230+) and exposes **backtesting only**:
the tools that send real orders are blocked, so an agent can research strategies on your machine without
being able to trade.

<p align="center"><img src="docs/images/agent-session.svg" alt="An agent testing an EA through MT5-Agent-Backtester" width="100%"></p>

---

## Contents

1. [Requirements](#requirements)
2. [Setup in 4 steps](#setup-in-4-steps)
3. [Your first backtest](#your-first-backtest)
4. [Use it from an AI agent](#use-it-from-an-ai-agent)
5. [Command reference](#command-reference)
6. [Python API](#python-api)
7. [Configuration](#configuration)
8. [Troubleshooting](#troubleshooting)
9. [How it works](#how-it-works)
10. [Extending](#extending)
11. [Development](#development)

---

## Requirements

- **MetaTrader 5, build 6230 or newer** (Windows, or macOS through the official MetaQuotes installer)
- **Python 3.10+**
- The EA you want to test, compiled (`.ex5`) inside the terminal's `MQL5\Experts` folder

The examples below use *Moving Average*, the sample EA that comes with every MetaTrader 5 install, so you
can try everything without writing any code.

---

## Setup in 4 steps

**1. Turn on the MCP server in MetaTrader 5**

Open **Tools → Options → MCP**, enable the server and click **Generate** to create a key.
Copy the key, then **restart MetaTrader 5** (a new key is only accepted after a restart).

**2. Install**

```bash
pip install "mt5-agent-backtester[plot] @ git+https://github.com/sergiomeneguzzo/MT5-Agent-Backtester"
```

The `[plot]` extra adds charts. Leave it out if you only need the numbers.

**3. Add your key**

Create a file called `.env` in the folder you work from:

```bash
MT5_MCP_KEY=paste-your-key-here
```

**4. Check the connection** (MetaTrader 5 must be open)

```bash
mt5agent doctor
```

```
check                 value
────────────────────  ──────────────────────────
connected             True
url                   http://127.0.0.1:22346/mcp
build                 6230
can_run_backtest      True
can_run_optimization  True
trading_tools         blocked
```

That's it.

---

## Your first backtest

```bash
mt5agent backtest "Examples/Moving Average/Moving Average" EURUSD H1 2020-01-01 2025-12-31 --plot equity.png
```

The arguments are: **EA**, **symbol**, **timeframe**, **start date**, **end date**. The EA path is relative to
`MQL5\Experts`, without the `.ex5` extension.

<p align="center"><img src="docs/images/terminal-backtest.svg" alt="Backtest output" width="85%"></p>
<p align="center"><img src="docs/images/equity.png" alt="Equity curve and drawdown" width="100%"></p>

**Change the EA inputs** with `-p Name=value`:

```bash
mt5agent backtest "Examples/Moving Average/Moving Average" EURUSD H1 2020-01-01 2025-12-31 -p MovingPeriod=20
```

**Optimize** by giving a range with `-p Name=start:stop:step`:

```bash
mt5agent optimize "Examples/Moving Average/Moving Average" EURUSD H1 2020-01-01 2025-12-31 \
    -p MovingPeriod=10:100:10 -p MovingShift=0:10:2 --plot heatmap.png
```

<p align="center"><img src="docs/images/terminal-optimize.svg" alt="Optimization output" width="90%"></p>
<p align="center"><img src="docs/images/heatmap.png" alt="Profit factor heatmap" width="100%"></p>

**Check that the result holds up** with a walk-forward: it re-optimizes on every 2-year window, trades the
winner on the following year it has never seen, and joins those years together.

```bash
mt5agent walkforward "Examples/Moving Average/Moving Average" EURUSD H1 2020-01-01 2026-01-01 \
    -p MovingPeriod=10:100:10 -p MovingShift=0:10:2 --is-months 24 --oos-months 12 --plot walkforward.png
```

> The numbers in these images are a real run of the sample EA (EURUSD H1, 2020–2025, open prices).
> It loses money, which is what makes it a useful example.

---

## Use it from an AI agent

The install also adds `mt5agent-mcp`, an MCP server you can plug into any agent.

**Claude Code**

```bash
claude mcp add mt5-backtester -e MT5_MCP_KEY=paste-your-key-here -- mt5agent-mcp
```

**Cursor, Windsurf or any other MCP client**: add this to the client's MCP config file.

```json
{
  "mcpServers": {
    "mt5-backtester": {
      "command": "mt5agent-mcp",
      "env": { "MT5_MCP_KEY": "paste-your-key-here" }
    }
  }
}
```

Then just ask, for example: *"Backtest the Moving Average EA on EURUSD H1 from 2020 to 2025, then check whether
optimizing MovingPeriod helps out-of-sample."*

The agent gets these tools:

| Tool | What it does |
|---|---|
| `list_experts` | lists the compiled EAs |
| `expert_inputs` | shows an EA's inputs, version and build time |
| `run_backtest` | one backtest: profit, profit factor, drawdown, trades, yearly returns |
| `run_optimization` | grid of inputs: number of profitable passes and the best ones |
| `run_walk_forward` | walk-forward: parameters per window and the out-of-sample result |

[`examples/claude_code/CLAUDE.md`](examples/claude_code/CLAUDE.md) is a ready-made set of instructions you
can drop into your project so the agent follows good testing habits.

---

## Command reference

Add `--json` before any command to get machine-readable output.

| Command | Example |
|---|---|
| `doctor` | `mt5agent doctor` |
| `experts` | `mt5agent experts --filter Moving` |
| `inputs` | `mt5agent inputs "Examples/Moving Average/Moving Average"` |
| `backtest` | `mt5agent backtest <EA> <SYMBOL> <TF> <START> <END> [-p Name=value] [--plot file.png] [--save report.xlsx]` |
| `optimize` | `mt5agent optimize <EA> <SYMBOL> <TF> <START> <END> -p Name=start:stop:step [--criterion profit_factor]` |
| `walkforward` | `mt5agent walkforward <EA> <SYMBOL> <TF> <START> <END> -p Name=start:stop:step [--is-months 24 --oos-months 6]` |
| `report` | `mt5agent report report.xlsx` (reads a saved report, MetaTrader 5 not needed) |
| `tools` | `mt5agent tools` (MCP tools of the terminal, trading tools hidden) |

Options shared by `backtest`, `optimize` and `walkforward`:

| Option | Default | Values |
|---|---|---|
| `--model` | `open prices` | `open prices`, `m1 ohlc`, `every tick`, `real ticks` |
| `--deposit` | `10000` | any amount |
| `--leverage` | `100` | any integer |

---

## Python API

```python
from mt5agent import MT5Client, Range, Tester

tester = Tester(MT5Client.connect())

run = tester.backtest("Examples/Moving Average/Moving Average", "EURUSD", "H1", "2020-01-01", "2025-12-31",
                      inputs={"MovingPeriod": 12})
run.stats["profit_factor"]        # numbers from MetaTrader 5
run.report.trades                 # every closed trade
run.report.yearly_returns()       # {2020: 1.32, 2021: -8.7, ...}

opt = tester.optimize("Examples/Moving Average/Moving Average", "EURUSD", "H1", "2020-01-01", "2025-12-31",
                      inputs={"MovingPeriod": Range(10, 100, 10), "MovingShift": Range(0, 10, 2)})
opt.result.best(by="Profit Factor", min_trades=200)

wf = tester.walk_forward("Examples/Moving Average/Moving Average", "EURUSD", "H1", "2020-01-01", "2026-01-01",
                         inputs={"MovingPeriod": Range(10, 100, 10)}, is_months=24, oos_months=12)
wf.summary()
```

Complete scripts are in [`examples/`](examples/).

---

## Configuration

Everything machine-specific is in **one file**: [`src/mt5agent/config.py`](src/mt5agent/config.py).
You normally don't edit it: set the values in `.env` or as environment variables instead.

| Variable | Default | Meaning |
|---|---|---|
| `MT5_MCP_KEY` | *(required)* | key from Tools → Options → MCP |
| `MT5_MCP_URL` | `http://127.0.0.1:22346/mcp` | address of the terminal's MCP server |
| `MT5_MCP_TIMEOUT` | `3600` | seconds to wait for long optimizations |
| `METAEDITOR_MCP_URL`, `METAEDITOR_MCP_KEY` | `http://127.0.0.1:22345/mcp` | MetaEditor server (optional) |

A template is in [`.env.example`](.env.example). Environment variables take priority over `.env`, and `.env`
is searched for from the current folder upward.

Defaults for model, deposit, leverage and the prefix of temporary files are at the top of the same
`config.py`. You can also pass the settings directly in code:

```python
from mt5agent import MT5Client, Settings

client = MT5Client(Settings(url="http://127.0.0.1:22346/mcp", key="..."))
```

---

## Troubleshooting

| Message | Fix |
|---|---|
| `MT5_MCP_KEY is not set` | create `.env` with your key (step 3) |
| `Cannot reach http://127.0.0.1:22346/mcp` | open MetaTrader 5 and check that MCP is enabled in Tools → Options → MCP |
| `401 Unauthorized` | the key is wrong, or you generated a new one and haven't restarted MetaTrader 5 |
| an error about the `.ex5` path | the EA path is wrong: run `mt5agent experts` to see the exact names |
| a test takes longer than expected | real-tick tests on many years are slow, so try `--model "open prices"` first |

---

## How it works

<p align="center"><img src="docs/images/architecture.svg" alt="Architecture" width="100%"></p>

For each run the library writes a tester config and an inputs file inside `MQL5\Profiles\Tester`, starts the
test, waits for it, downloads the report and reads every deal. It then deletes its temporary files and closes
any chart the test opened.

**Safety**

- Tools starting with `trade_` are refused and hidden. Enabling them requires
  `MT5Client(..., allow_trading=True)` in your own code. The agent server never does this.
- The MCP server only listens on `127.0.0.1`.
- The key is never printed. It is left out of `repr()`, logs and tracebacks.
- Broker server, company and account fields are removed from parsed reports.
- Only charts that appeared during the run and have nothing attached are closed. Charts running an EA are
  never touched.

**Project layout**

```
src/mt5agent/
├── config.py        settings and defaults
├── client.py        connection to the MetaTrader 5 MCP server
├── tester.py        backtest, optimize, walk_forward
├── walkforward.py   in-sample / out-of-sample windows
├── inputs.py        EA inputs and optimization ranges
├── metrics.py       profit factor, drawdown, yearly returns
├── reports/         readers for the .xlsx and .xml reports
├── cli/             the mt5agent command
├── mcp/             the mt5agent-mcp server for agents
└── plots.py         charts
```

---

## Extending

Commands and agent tools are plain functions with a decorator, so you add one without touching anything else.

New agent tool, in [`src/mt5agent/mcp/tools.py`](src/mt5agent/mcp/tools.py):

```python
@tool("compare_models", "Run the same backtest with open prices and real ticks.", run_schema())
def compare_models(tester: Tester, args: dict) -> dict:
    positional, options = run_args(args)
    runs = {m: tester.backtest(*positional, **{**options, "model": m}) for m in ("open prices", "real ticks")}
    return {m: run.summary() for m, run in runs.items()}
```

New command, in [`src/mt5agent/cli/commands.py`](src/mt5agent/cli/commands.py):

```python
@command("charts", "list open charts")
def charts(ctx: Context) -> None:
    items = ctx.client.call("list_open_charts").get("charts", [])
    ctx.out.table(("id", "symbol"), [(c["chart_id"], c["symbol"]) for c in items])
```

---

## Development

```bash
git clone https://github.com/sergiomeneguzzo/MT5-Agent-Backtester
cd MT5-Agent-Backtester
pip install -e ".[dev]"
pytest -q
```

The 38 tests run without MetaTrader 5: a fake server replays real Strategy Tester output.
`docs/run_demo.py` and `docs/make_images.py` regenerate the images in this README from a live terminal.

**Roadmap**: multi-symbol portfolios, Monte Carlo on out-of-sample trades, compiling `.mq5` before testing,
real-tick vs OHLC comparison, PyPI release.

---

Backtests do not guarantee future results and nothing here is financial advice.
[MIT License](LICENSE) © Sergio Meneguzzo
