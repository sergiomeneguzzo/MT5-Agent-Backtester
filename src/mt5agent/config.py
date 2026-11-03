from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

TERMINAL_URL = "http://127.0.0.1:22346/mcp"
EDITOR_URL = "http://127.0.0.1:22345/mcp"
REQUEST_TIMEOUT = 3600

ENV_TERMINAL_URL = "MT5_MCP_URL"
ENV_TERMINAL_KEY = "MT5_MCP_KEY"
ENV_EDITOR_URL = "METAEDITOR_MCP_URL"
ENV_EDITOR_KEY = "METAEDITOR_MCP_KEY"
ENV_TIMEOUT = "MT5_MCP_TIMEOUT"

DEFAULT_MODEL = "open prices"
DEFAULT_DEPOSIT = 10_000.0
DEFAULT_LEVERAGE = 100
FILE_PREFIX = "mt5agent"


@dataclass(frozen=True)
class Settings:
    url: str = TERMINAL_URL
    key: str = field(default="", repr=False)
    timeout: float = REQUEST_TIMEOUT

    @classmethod
    def from_env(cls, editor: bool = False, dotenv: str | os.PathLike | None = None) -> Settings:
        env = _read_dotenv(Path(dotenv) if dotenv else _find_dotenv(Path.cwd()))
        env.update({k: v for k, v in os.environ.items() if v})
        url_var, key_var = (ENV_EDITOR_URL, ENV_EDITOR_KEY) if editor else (ENV_TERMINAL_URL, ENV_TERMINAL_KEY)
        key = env.get(key_var, "")
        if not key:
            raise RuntimeError(
                f"{key_var} is not set. Generate a key in MetaTrader 5 (Tools > Options > MCP), "
                "restart the terminal and add it to .env (see .env.example)."
            )
        return cls(
            url=env.get(url_var) or (EDITOR_URL if editor else TERMINAL_URL),
            key=key,
            timeout=float(env.get(ENV_TIMEOUT) or REQUEST_TIMEOUT),
        )


def _find_dotenv(start: Path) -> Path | None:
    return next((p / ".env" for p in (start, *start.parents) if (p / ".env").is_file()), None)


def _read_dotenv(path: Path | None) -> dict[str, str]:
    if not path or not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values
