"""FastMCP server construction and executable entry point."""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging
from collections.abc import AsyncIterator
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from supabase_mcp.config import Settings
from supabase_mcp.database import DatabaseClient
from supabase_mcp.tools import describe_table, health_check, list_allowed_tables, select_rows


def load_settings() -> Settings:
    """Load environment-backed settings (Pydantic's generated signature appears required)."""
    return Settings()  # type: ignore[call-arg]


@lifespan
async def app_lifespan(_server: FastMCP[Any]) -> AsyncIterator[dict[str, Any]]:
    """Create and dispose the one shared database client for this server process."""
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    database = DatabaseClient(settings)
    await database.start()
    try:
        yield {"database": database}
    finally:
        await database.stop()


mcp = FastMCP("Supabase Read-Only", lifespan=app_lifespan)
mcp.tool(health_check)
mcp.tool(list_allowed_tables)
mcp.tool(describe_table)
mcp.tool(select_rows)


def main() -> None:
    """Run using environment-configured stdio or Streamable HTTP transport."""
    settings = load_settings()
    if settings.transport == "http":
        mcp.run(transport="http", host=settings.host, port=settings.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
