"""Allowlisted schema discovery tools."""

from __future__ import annotations

import logging

from fastmcp import Context

from supabase_mcp.errors import InvalidSelectionError
from supabase_mcp.models import AllowedTablesResult, DescribeTableResult, PublicError
from supabase_mcp.tools._context import database_from_context

logger = logging.getLogger(__name__)


async def list_allowed_tables(ctx: Context) -> AllowedTablesResult:
    """List only configured and validated tables/views; use before describing or selecting."""
    try:
        objects = database_from_context(ctx).list_allowed_objects()
        return AllowedTablesResult(ok=True, objects=objects, object_count=len(objects))
    except Exception as exc:
        logger.warning("Allowed-object discovery failed (%s)", type(exc).__name__)
        return AllowedTablesResult(
            ok=False,
            error=PublicError(code="server_error", message="Allowed objects could not be listed."),
        )


async def describe_table(schema: str, table: str, ctx: Context) -> DescribeTableResult:
    """Describe safe column metadata for one allowlisted schema/table; rejects all others."""
    try:
        columns = list(database_from_context(ctx).describe_table(schema, table))
        return DescribeTableResult(ok=True, schema=schema, table=table, columns=columns)
    except InvalidSelectionError as exc:
        return DescribeTableResult(
            ok=False,
            schema=schema,
            table=table,
            error=PublicError(code=exc.code, message=exc.safe_message),
        )
    except Exception as exc:
        logger.warning("Allowlisted object description failed (%s)", type(exc).__name__)
        return DescribeTableResult(
            ok=False,
            schema=schema,
            table=table,
            error=PublicError(
                code="server_error", message="The object description could not be completed."
            ),
        )
