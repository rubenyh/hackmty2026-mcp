"""FastMCP server construction and executable entry point."""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging
from collections.abc import AsyncIterator, Callable
from importlib.resources import files
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan
from mcp.types import ToolAnnotations

from supabase_mcp.a2ui_support.constants import A2UI_MIME_TYPE
from supabase_mcp.a2ui_support.models import SurfaceSpec
from supabase_mcp.a2ui_support.response import ui_metadata
from supabase_mcp.a2ui_support.surfaces import (
    ACTION_SURFACES,
    CHAT_MESSAGE_SURFACE,
    DATA_CHART_SURFACE,
    DATABASE_OVERVIEW_SURFACE,
    FINANCIAL_VIEW_SURFACE,
    SURFACE_REGISTRY,
)
from supabase_mcp.config import Settings
from supabase_mcp.database import DatabaseClient
from supabase_mcp.tools import (
    FINANCIAL_TOOLS,
    a2ui_action,
    a2ui_error,
    chat_message,
    chat_message_resource,
    data_chart_resource,
    database_overview,
    database_overview_resource,
    describe_table,
    financial_view_resource,
    health_check,
    list_allowed_tables,
    present_financial_view,
    select_rows,
    visualize_allowed_data,
)
from supabase_mcp.tools.action_forms import a2ui_form


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
mcp.tool(a2ui_form, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False))


def action_resource_reader(surface: SurfaceSpec) -> Callable[[], str]:
    def read() -> str:
        return SURFACE_REGISTRY.serialized_template(surface)

    return read


for action_name, action_surface in ACTION_SURFACES.items():
    mcp.resource(
        action_surface.resource_uri, name=action_name.replace(".", "_"), mime_type=A2UI_MIME_TYPE
    )(action_resource_reader(action_surface))


def input_contract_resource() -> str:
    return files("supabase_mcp.a2ui_actions").joinpath("inputs.json").read_text()


def action_contract_resource() -> str:
    return files("supabase_mcp.a2ui_actions").joinpath("actions.json").read_text()


mcp.resource("a2ui://actions/inputs", mime_type="application/json")(input_contract_resource)
mcp.resource("a2ui://actions/registry", mime_type="application/json")(action_contract_resource)
mcp.tool(health_check)
mcp.tool(list_allowed_tables)
mcp.tool(describe_table)
mcp.tool(select_rows)
for financial_tool in FINANCIAL_TOOLS:
    mcp.tool(
        financial_tool,
        annotations=ToolAnnotations(
            title=f"{financial_tool.__name__.replace('_', ' ').title()} / Herramienta financiera",
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
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
    visualize_allowed_data,
    meta=ui_metadata(DATA_CHART_SURFACE),
    annotations=ToolAnnotations(
        title="Visualize allowed data",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
mcp.tool(
    present_financial_view,
    meta=ui_metadata(FINANCIAL_VIEW_SURFACE),
    annotations=ToolAnnotations(
        title="Present financial view",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
mcp.tool(
    chat_message,
    meta=ui_metadata(CHAT_MESSAGE_SURFACE),
    annotations=ToolAnnotations(
        title="Present chat message",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
mcp.tool(
    a2ui_action,
    annotations=ToolAnnotations(
        title="Handle user-confirmed A2UI action",
        read_only_hint=False,
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
mcp.resource(
    DATA_CHART_SURFACE.resource_uri,
    name="data_chart_a2ui",
    title=DATA_CHART_SURFACE.title,
    description=DATA_CHART_SURFACE.description,
    mime_type=A2UI_MIME_TYPE,
)(data_chart_resource)
mcp.resource(
    CHAT_MESSAGE_SURFACE.resource_uri,
    name="chat_message_a2ui",
    title=CHAT_MESSAGE_SURFACE.title,
    description=CHAT_MESSAGE_SURFACE.description,
    mime_type=A2UI_MIME_TYPE,
)(chat_message_resource)
mcp.resource(
    FINANCIAL_VIEW_SURFACE.resource_uri,
    name="financial_view_a2ui",
    title=FINANCIAL_VIEW_SURFACE.title,
    description=FINANCIAL_VIEW_SURFACE.description,
    mime_type=A2UI_MIME_TYPE,
)(financial_view_resource)


def main() -> None:
    """Run using environment-configured stdio or Streamable HTTP transport."""
    settings = load_settings()
    if settings.transport == "http":
        mcp.run(transport="http", host=settings.host, port=settings.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
