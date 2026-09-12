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
from mcp.types import ToolAnnotations

from supabase_mcp.a2ui_support.constants import A2UI_MIME_TYPE
from supabase_mcp.a2ui_support.response import ui_metadata
from supabase_mcp.a2ui_support.surfaces import DATABASE_OVERVIEW_SURFACE
from supabase_mcp.config import Settings
from supabase_mcp.database import DatabaseClient
from supabase_mcp.tools import (
    a2ui_action,
    a2ui_error,
    database_overview,
    database_overview_resource,
    describe_table,
    health_check,
    list_allowed_tables,
    select_rows,
)


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
mcp.tool(
    database_overview,
    meta=ui_metadata(DATABASE_OVERVIEW_SURFACE),
    annotations=ToolAnnotations(
        title="Database overview",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
mcp.tool(
    a2ui_action,
    annotations=ToolAnnotations(
        title="Handle A2UI action",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
mcp.tool(
    a2ui_error,
    annotations=ToolAnnotations(
        title="Report A2UI client error",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
mcp.resource(
    DATABASE_OVERVIEW_SURFACE.resource_uri,
    name="database_overview_a2ui",
    title=DATABASE_OVERVIEW_SURFACE.title,
    description=DATABASE_OVERVIEW_SURFACE.description,
    mime_type=A2UI_MIME_TYPE,
)(database_overview_resource)


def main() -> None:
    """Run using environment-configured stdio or Streamable HTTP transport."""
    settings = load_settings()
    if settings.transport == "http":
        mcp.run(transport="http", host=settings.host, port=settings.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
