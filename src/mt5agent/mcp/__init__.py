from .server import Server
from .tools import TOOLS, Tool, tool


def main() -> None:
    Server().serve()


__all__ = ["TOOLS", "Server", "Tool", "main", "tool"]
