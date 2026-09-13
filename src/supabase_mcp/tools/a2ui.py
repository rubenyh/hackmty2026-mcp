"""A2UI-enabled read-only overview, action, error, and resource handlers."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.tools import ToolResult
from mcp.types import TextContent
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from supabase_mcp.a2ui_support.actions import (
    A2UIActionCall,
    ActionDispatchError,
    ActionRegistry,
    RefreshDatabaseOverviewContext,
    RegisteredAction,
    RequestFinancialViewContext,
)
from supabase_mcp.a2ui_support.constants import (
    CHAT_MESSAGE_MAX_LENGTH,
    DATABASE_OVERVIEW_DEFAULT_LIMIT,
    PRESENT_FINANCIAL_VIEW_ACTION,
    PRESENT_FINANCIAL_VIEW_COMPONENT_ID,
    REFRESH_DATABASE_OVERVIEW_ACTION,
    REFRESH_DATABASE_OVERVIEW_COMPONENT_ID,
)
from supabase_mcp.a2ui_support.mappers import (
    database_overview_data_model,
    database_overview_fallback,
)
from supabase_mcp.a2ui_support.response import A2UIResponseFactory
from supabase_mcp.a2ui_support.surfaces import (
    CHAT_MESSAGE_SURFACE,
    DATA_CHART_SURFACE,
    DATABASE_OVERVIEW_SURFACE,
    FINANCIAL_VIEW_SURFACE,
    SURFACE_REGISTRY,
)
from supabase_mcp.a2ui_support.validation import A2UIValidationError, A2UIValidator
from supabase_mcp.database import DatabaseClient
from supabase_mcp.errors import InvalidSelectionError
from supabase_mcp.models import FinancialSurfaceRequest, UserScope, VisualizeAllowedDataRequest
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
from supabase_mcp.tools.action_forms import action_outcome, register_form_actions
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
_chat_message_factory = A2UIResponseFactory(CHAT_MESSAGE_SURFACE)
_financial_view_factory = A2UIResponseFactory(FINANCIAL_VIEW_SURFACE)
_a2ui_validator = A2UIValidator()
ACTION_REGISTRY = ActionRegistry(SURFACE_REGISTRY)
register_form_actions(ACTION_REGISTRY)


def database_overview_resource() -> str:
    """Return the cached static database-overview A2UI template."""
    return SURFACE_REGISTRY.serialized_template(DATABASE_OVERVIEW_SURFACE)


def data_chart_resource() -> str:
    """Return the cached static finance-catalog chart template."""
    return SURFACE_REGISTRY.serialized_template(DATA_CHART_SURFACE)


def chat_message_resource() -> str:
    """Return the cached static chat-message A2UI template."""
    return SURFACE_REGISTRY.serialized_template(CHAT_MESSAGE_SURFACE)


def financial_view_resource() -> str:
    """Return the cached stable Finance v2 BankingView composition."""
    return SURFACE_REGISTRY.serialized_template(FINANCIAL_VIEW_SURFACE)


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
    except SQLAlchemyError as exc:
        logger.warning("Allowed data visualization database failure (%s)", type(exc).__name__)
        message = "The database request could not be completed."
        return ToolResult(
            content=[TextContent(text=message)],
            structured_content={
                "ok": False,
                "error": {"code": "database_error", "message": message},
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


async def present_financial_view(request: FinancialSurfaceRequest) -> ToolResult:
    """Validate and present one semantic Finance v2 BankingView surface."""
    try:
        _a2ui_validator.validate_banking_view(request.view)
        title = request.view.get("title")
        if not isinstance(title, str):
            raise A2UIValidationError("BankingView title must be a string")
        data_model = {
            "view": request.view,
            "actionLabel": request.action_label,
            "requestIntent": request.request_intent.value,
        }
        return _financial_view_factory.build(
            fallback_text=title,
            data_model=data_model,
            structured_content={
                "ok": True,
                "surfaceId": FINANCIAL_VIEW_SURFACE.surface_id,
                **data_model,
            },
        )
    except A2UIValidationError:
        message = "The financial view does not match the Finance v2 contract."
        return ToolResult(
            content=[TextContent(text=message)],
            structured_content={
                "ok": False,
                "error": {"code": "invalid_financial_view", "message": message},
            },
            is_error=True,
        )


class ChatMessageRequest(BaseModel):
    """One plain conversational reply to present as an A2UI text surface."""

    text: Annotated[str, Field(min_length=1, max_length=CHAT_MESSAGE_MAX_LENGTH)]


async def chat_message(request: ChatMessageRequest) -> ToolResult:
    """Wrap one drafted conversational reply as a validated A2UI text surface.

    Every final answer must reach the client as A2UI, never as bare text: this
    is the only tool a plain conversational turn (no chart, no overview) is
    allowed to end on.
    """
    text = request.text.strip()
    try:
        return _chat_message_factory.build(fallback_text=text, data_model={"message": text})
    except Exception as exc:
        logger.warning("Chat message presentation failed (%s)", type(exc).__name__)
        return ToolResult(
            content=[TextContent(text=text)],
            structured_content={
                "ok": False,
                "error": {"code": "server_error", "message": "The message could not be presented."},
            },
            is_error=True,
        )


async def _refresh_database_overview(
    _call: A2UIActionCall,
    context: BaseModel,
    _trusted_scope: UserScope | None,
    database: DatabaseClient,
) -> ToolResult:
    if not isinstance(context, RefreshDatabaseOverviewContext):
        raise ActionDispatchError("invalid_action_context", "The A2UI action context is invalid.")
    return _overview_tool_result(get_database_overview(database, context.limit))


async def _request_financial_view(
    call: A2UIActionCall,
    context: BaseModel,
    trusted_scope: UserScope | None,
    _database_client: DatabaseClient,
) -> ToolResult:
    if not isinstance(context, RequestFinancialViewContext) or trusted_scope is None:
        raise ActionDispatchError("invalid_action_context", "The A2UI action context is invalid.")
    request = context.model_dump(mode="json", by_alias=True, exclude_none=True)
    normalized = {
        "ok": True,
        "action": call.model_dump(mode="json", by_alias=True),
        "request": request,
        "trustedScope": trusted_scope.model_dump(mode="json", by_alias=True),
    }
    return ToolResult(
        content=[TextContent(text=f"Requested financial view: {context.intent.value}.")],
        structured_content=normalized,
    )


ACTION_REGISTRY.register(
    RegisteredAction(
        name=REFRESH_DATABASE_OVERVIEW_ACTION,
        surface_id=DATABASE_OVERVIEW_SURFACE.surface_id,
        source_component_id=REFRESH_DATABASE_OVERVIEW_COMPONENT_ID,
        context_model=RefreshDatabaseOverviewContext,
        handler=_refresh_database_overview,
    )
)
ACTION_REGISTRY.register(
    RegisteredAction(
        name=PRESENT_FINANCIAL_VIEW_ACTION,
        surface_id=FINANCIAL_VIEW_SURFACE.surface_id,
        source_component_id=PRESENT_FINANCIAL_VIEW_COMPONENT_ID,
        context_model=RequestFinancialViewContext,
        handler=_request_financial_view,
        requires_trusted_scope=True,
    )
)


async def a2ui_action(
    name: A2UIName,
    surfaceId: A2UIName,
    sourceComponentId: A2UIName,
    timestamp: A2UITimestamp,
    context: dict[str, Any],
    ctx: Context,
    trustedScope: UserScope | None = None,
    actionProof: str | None = None,
) -> ToolResult:
    """Dispatch one allowlisted A2UI user action with trusted ownership."""
    try:
        database = _database(ctx)
        if name in {"budget.create", "budget.update", "savings_goal.create", "savings_goal.update"}:
            from supabase_mcp.a2ui_actions.proof import verify_action_proof

            verify_action_proof(
                database.settings.actions_secret,
                actionProof,
                {
                    "name": name,
                    "surfaceId": surfaceId,
                    "sourceComponentId": sourceComponentId,
                    "timestamp": timestamp,
                    "context": context,
                    "user_id": str(trustedScope.user_id) if trustedScope else None,
                },
            )
        return await ACTION_REGISTRY.dispatch(
            name=name,
            surface_id=surfaceId,
            source_component_id=sourceComponentId,
            timestamp=timestamp,
            context=context,
            database=_database(ctx),
            trusted_scope=trustedScope,
        )
    except ActionDispatchError as exc:
        logger.info("A2UI action rejected code=%s", exc.code)
        return action_outcome(False, exc.safe_message, exc.code)
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
