"""Structured, read-only row selection tool."""

from __future__ import annotations

import logging

from fastmcp import Context
from pydantic import ValidationError

from supabase_mcp.errors import InvalidSelectionError
from supabase_mcp.models import FilterCondition, OrderBy, PublicError, SelectRequest, SelectResult
from supabase_mcp.tools.health import _database

logger = logging.getLogger(__name__)


async def select_rows(
    schema: str,
    table: str,
    ctx: Context,
    columns: list[str] | None = None,
    filters: list[FilterCondition] | None = None,
    order_by: list[OrderBy] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> SelectResult:
    """Select bounded rows from an allowlisted object using typed filters, never arbitrary SQL."""
    effective_limit = limit if limit is not None else 50
    try:
        database = _database(ctx)
        effective_limit = limit if limit is not None else database.settings.default_limit
        request = SelectRequest(
            schema=schema,
            table=table,
            columns=columns,
            filters=filters or [],
            order_by=order_by or [],
            limit=limit,
            offset=offset,
        )
        rows, effective_limit, truncated = await database.select_rows(request)
        return SelectResult(
            ok=True,
            rows=rows,
            row_count=len(rows),
            limit=effective_limit,
            offset=offset,
            truncated=truncated,
        )
    except InvalidSelectionError as exc:
        return SelectResult(
            ok=False,
            limit=effective_limit,
            offset=offset,
            error=PublicError(code=exc.code, message=exc.safe_message),
        )
    except ValidationError:
        return SelectResult(
            ok=False,
            limit=max(effective_limit, 0),
            offset=max(offset, 0),
            error=PublicError(code="invalid_request", message="The selection request is invalid."),
        )
    except Exception as exc:
        logger.warning("Row selection failed for an allowlisted object (%s)", type(exc).__name__)
        return SelectResult(
            ok=False,
            limit=effective_limit,
            offset=offset,
            error=PublicError(
                code="database_error", message="The database request could not be completed."
            ),
        )
