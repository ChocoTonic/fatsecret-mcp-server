"""MCP server construction."""

from __future__ import annotations

from mcp.server import MCPServer

from . import __version__
from .runtime import Runtime
from .settings import Settings
from .tools import register_tools


def create_server(
    settings: Settings | None = None, *, runtime: Runtime | None = None
) -> MCPServer:
    configuration = settings or Settings.from_env()
    execution = runtime or Runtime(configuration)
    server = MCPServer(
        name="fatsecret-mcp-server",
        title="FatSecret MCP Server",
        description=(
            "Independent access to FatSecret Platform data and experimental "
            "member recipe/RDI workflows."
        ),
        version=__version__,
        instructions=(
            "Use exact food IDs for member recipe ingredients. Supply a unique "
            "idempotency key for every mutation and reuse it after a timeout. "
            "Member-site grams must be whole numbers. Recipe diary entries "
            "snapshot nutrition; delete and re-add them after recipe changes."
        ),
    )
    register_tools(server, execution, configuration.profile)
    return server
