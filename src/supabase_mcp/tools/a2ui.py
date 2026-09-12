"""A2UI-enabled read-only overview, action, error, and resource handlers."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.tools import ToolResult
from mcp.types import TextContent
from pydantic import BaseModel, Field

from supabase_mcp.a2ui_support.actions import (
    ActionDispatchError,
    ActionRegistry,
    RefreshDatabaseOverviewContext,
    RegisteredAction,
)
from supabase_mcp.a2ui_support.constants import (
    DATABASE_OVERVIEW_DEFAULT_LIMIT,
    REFRESH_DATABASE_OVERVIEW_ACTION,
    REFRESH_DATABASE_OVERVIEW_COMPONENT_ID,
)
from supabase_mcp.a2ui_support.mappers import (
    database_overview_data_model,
    database_overview_fallback,
)
from supabase_mcp.a2ui_support.response import A2UIResponseFactory
from supabase_mcp.a2ui_support.surfaces import (
    DATA_CHART_SURFACE,
    DATABASE_OVERVIEW_SURFACE,
    SURFACE_REGISTRY,
)
from supabase_mcp.database import DatabaseClient
from supabase_mcp.errors import InvalidSelectionError
from supabase_mcp.models import VisualizeAllowedDataRequest
from supabase_mcp.services.data_chart import (
    ChartMappingError,
    chart_data_model,
    chart_fallback,
    get_data_chart,
)
from supabase_mcp.services.database_overview import (
    DATABASE_OVERVIEW_MAX_LIMIT,
    DatabaseOverview,
    get_database_overview,
)
from supabase_mcp.tools.health import _database

logger = logging.getLogger(__name__)

OverviewLimit = Annotated[
    int,
    Field(ge=1, le=DATABASE_OVERVIEW_MAX_LIMIT, description="Maximum objects shown in the UI"),
]
A2UIName = Annotated[str, Field(min_length=1, max_length=128)]
A2UITimestamp = Annotated[str, Field(min_length=1, max_length=64)]
A2UIErrorPath = Annotated[str, Field(max_length=512)]
A2UIErrorMessage = Annotated[str, Field(max_length=2_000)]

_overview_factory = A2UIResponseFactory(DATABASE_OVERVIEW_SURFACE)
_chart_factory = A2UIResponseFactory(DATA_CHART_SURFACE)
ACTION_REGISTRY = ActionRegistry(SURFACE_REGISTRY)


def database_overview_resource() -> str:
    """Return the cached static database-overview A2UI template."""
    return SURFACE_REGISTRY.serialized_template(DATABASE_OVERVIEW_SURFACE)


def data_chart_resource() -> str:
    """Return the cached static finance-catalog chart template."""
    return SURFACE_REGISTRY.serialized_template(DATA_CHART_SURFACE)


def _overview_tool_result(overview: DatabaseOverview) -> ToolResult:
    return _overview_factory.build(
        fallback_text=database_overview_fallback(overview),
        data_model=database_overview_data_model(overview),
        structured_content=overview.structured_content(),
    )


async def database_overview(
    ctx: Context, limit: OverviewLimit = DATABASE_OVERVIEW_DEFAULT_LIMIT
) -> ToolResult:
    """Show a bounded A2UI overview of the allowlisted database tables and views."""
    try:
        return _overview_tool_result(get_database_overview(_database(ctx), limit))
    except Exception as exc:
        logger.warning("Database overview failed (%s)", type(exc).__name__)
        return ToolResult(
            content=[TextContent(text="The database overview could not be generated.")],
            structured_content={
                "ok": False,
                "error": {
                    "code": "server_error",
                    "message": "The database overview could not be generated.",
                },
            },
            is_error=True,
        )


async def visualize_allowed_data(
    request: VisualizeAllowedDataRequest,
    ctx: Context,
) -> ToolResult:
    """Visualize selected columns from one reflected allowlisted table or view."""
    try:
        result = await get_data_chart(_database(ctx), request)
        return _chart_factory.build(
            fallback_text=chart_fallback(result),
            data_model=chart_data_model(result, request.title),
            structured_content=result.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
    except (InvalidSelectionError, ChartMappingError) as exc:
        logger.info("Allowed data visualization rejected code=%s", exc.code)
        return ToolResult(
            content=[TextContent(text=exc.safe_message)],
            structured_content={
                "ok": False,
                "error": {"code": exc.code, "message": exc.safe_message},
            },
            is_error=True,
        )
    except Exception as exc:
        logger.warning("Allowed data visualization failed (%s)", type(exc).__name__)
        return ToolResult(
            content=[TextContent(text="The requested data chart could not be generated.")],
            structured_content={
                "ok": False,
                "error": {
                    "code": "server_error",
                    "message": "The requested data chart could not be generated.",
                },
            },
            is_error=True,
        )


async def _refresh_database_overview(context: BaseModel, database: DatabaseClient) -> ToolResult:
    if not isinstance(context, RefreshDatabaseOverviewContext):
        raise ActionDispatchError("invalid_action_context", "The A2UI action context is invalid.")
    return _overview_tool_result(get_database_overview(database, context.limit))


ACTION_REGISTRY.register(
    RegisteredAction(
        name=REFRESH_DATABASE_OVERVIEW_ACTION,
        surface_id=DATABASE_OVERVIEW_SURFACE.surface_id,
        source_component_id=REFRESH_DATABASE_OVERVIEW_COMPONENT_ID,
        context_model=RefreshDatabaseOverviewContext,
        handler=_refresh_database_overview,
    )
)


async def a2ui_action(
    name: A2UIName,
    surfaceId: A2UIName,
    sourceComponentId: A2UIName,
    timestamp: A2UITimestamp,
    context: dict[str, Any],
    ctx: Context,
) -> ToolResult:
    """Dispatch one allowlisted, read-only A2UI user action."""
    try:
        return await ACTION_REGISTRY.dispatch(
            name=name,
            surface_id=surfaceId,
            source_component_id=sourceComponentId,
            timestamp=timestamp,
            context=context,
            database=_database(ctx),
        )
    except ActionDispatchError as exc:
        logger.info("A2UI action rejected code=%s", exc.code)
        return ToolResult(
            content=[TextContent(text=exc.safe_message)],
            structured_content={
                "ok": False,
                "error": {"code": exc.code, "message": exc.safe_message},
            },
            is_error=True,
        )
    except Exception as exc:
        logger.warning("A2UI action failed (%s)", type(exc).__name__)
        return ToolResult(
            content=[TextContent(text="The A2UI action could not be completed.")],
            structured_content={
                "ok": False,
                "error": {
                    "code": "action_failed",
                    "message": "The A2UI action could not be completed.",
                },
            },
            is_error=True,
        )


async def a2ui_error(
    code: A2UIName,
    surfaceId: A2UIName,
    path: A2UIErrorPath,
    message: A2UIErrorMessage,
) -> ToolResult:
    """Acknowledge a client-reported A2UI rendering or validation error safely."""
    known_surface = SURFACE_REGISTRY.get_by_id(surfaceId) is not None
    validation_failed = code == "VALIDATION_FAILED"
    logger.warning(
        "A2UI client error validation_failed=%s known_surface=%s path_present=%s message_length=%d",
        validation_failed,
        known_surface,
        bool(path),
        min(len(message), 10_000),
    )
    acknowledgement = (
        "Acknowledged an A2UI validation error. The textual fallback remains available."
        if validation_failed
        else "Acknowledged an A2UI client error. The textual fallback remains available."
    )
    return ToolResult(
        content=[TextContent(text=acknowledgement)],
        structured_content={
            "acknowledged": True,
            "validation_failed": validation_failed,
            "known_surface": known_surface,
        },
    )
