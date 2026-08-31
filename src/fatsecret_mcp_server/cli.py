"""Command-line entry point."""

from __future__ import annotations

import argparse
from typing import Literal, cast

from .server import create_server
from .settings import Profile, Settings


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="fatsecret-mcp-server")
    result.add_argument(
        "--profile",
        choices=("default", "member", "discovery", "diary", "bootstrap", "full"),
        help="Override FATSECRET_MCP_PROFILE for this process",
    )
    result.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    return result


def main() -> None:
    arguments = parser().parse_args()
    settings = Settings.from_env()
    if arguments.profile:
        settings = settings.model_copy(
            update={"profile": cast(Profile, arguments.profile)}
        )
    transport = cast(Literal["stdio", "streamable-http"], arguments.transport)
    create_server(settings).run(transport=transport)


if __name__ == "__main__":
    main()
