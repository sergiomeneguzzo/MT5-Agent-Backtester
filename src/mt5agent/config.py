"""Connection settings: environment variables first, then a local ``.env`` file.

Nothing here is ever printed or logged. Keys only work on 127.0.0.1 anyway,
but treat them like passwords.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TERMINAL_URL = "http://127.0.0.1:22346/mcp"
DEFAULT_EDITOR_URL = "http://127.0.0.1:22345/mcp"


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _find_dotenv(start: Path) -> Path | None:
    for folder in (start, *start.parents):
        candidate = folder / ".env"
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class Settings:
    url: str
    key: str

    @classmethod
    def load(cls, editor: bool = False, dotenv: str | os.PathLike | None = None) -> Settings:
        """Resolve URL + key for the terminal (default) or the MetaEditor server.

        Lookup order: ``MT5_MCP_URL`` / ``MT5_MCP_KEY`` (or ``METAEDITOR_MCP_*``)
        in the environment, then in ``dotenv`` or the first ``.env`` found walking
        up from the current directory.
        """
        prefix = "METAEDITOR" if editor else "MT5"
        path = Path(dotenv) if dotenv else _find_dotenv(Path.cwd())
        file_values = _read_dotenv(path) if path else {}

        def get(name: str) -> str | None:
            return os.environ.get(name) or file_values.get(name)

        url = get(f"{prefix}_MCP_URL") or (DEFAULT_EDITOR_URL if editor else DEFAULT_TERMINAL_URL)
        key = get(f"{prefix}_MCP_KEY")
        if not key:
            raise RuntimeError(
                f"{prefix}_MCP_KEY is not set. Generate a key in MetaTrader 5 "
                "(Tools > Options > MCP), restart the terminal and put it in .env "
                "(see .env.example)."
            )
        return cls(url=url, key=key)

    def __repr__(self) -> str:  # never leak the key in tracebacks / logs
        return f"Settings(url={self.url!r}, key='***')"
