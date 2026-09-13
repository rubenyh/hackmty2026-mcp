"""Shared execution boundary for financial MCP tools."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from fastmcp import Context
from fastmcp.tools import ToolResult
from mcp.types import TextContent
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from supabase_mcp.errors import SafeMCPError
from supabase_mcp.serialization import to_json_safe
from supabase_mcp.tools.health import _database

logger = logging.getLogger(__name__)
RequestT = TypeVar("RequestT", bound=BaseModel)


async def _run(
    operation: str,
    request: RequestT,
    ctx: Context,
    handler: Callable[[Any, RequestT], Awaitable[dict[str, Any]]],
) -> ToolResult:
    try:
        data = to_json_safe(await handler(_database(ctx), request))
        return ToolResult(
            content=[
                TextContent(text="Financial data retrieved. / Datos financieros consultados.")
            ],
            structured_content=data,
        )
    except SafeMCPError as exc:
        return ToolResult(
            content=[TextContent(text=exc.safe_message)],
            structured_content={
                "ok": False,
                "error": {"code": exc.code, "message": exc.safe_message},
            },
            is_error=True,
        )
    except SQLAlchemyError as exc:
        logger.warning(
            "Financial tool database failure operation=%s type=%s", operation, type(exc).__name__
        )
        message = (
            "The financial request could not be completed. / "
            "No se pudo completar la consulta financiera."
        )
        return ToolResult(
            content=[TextContent(text=message)],
            structured_content={
                "ok": False,
                "error": {"code": "database_error", "message": message},
            },
            is_error=True,
        )
    except Exception as exc:
        logger.warning("Financial tool failed operation=%s type=%s", operation, type(exc).__name__)
        message = (
            "The financial request could not be completed. / "
            "No se pudo completar la consulta financiera."
        )
        return ToolResult(
            content=[TextContent(text=message)],
            structured_content={"ok": False, "error": {"code": "server_error", "message": message}},
            is_error=True,
        )
