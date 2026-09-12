"""Database health tool."""

from __future__ import annotations

import logging

from fastmcp import Context

from mcp.src.supabase_mcp.database import DatabaseClient
from mcp.src.supabase_mcp.models import HealthResult, PublicError

logger = logging.getLogger(__name__)


def _database(ctx: Context) -> DatabaseClient:
    database = ctx.lifespan_context.get("database")
    if not isinstance(database, DatabaseClient):
        raise RuntimeError("database lifespan context is unavailable")
    return database


async def health_check(ctx: Context) -> HealthResult:
    """Check server and database availability with SELECT 1; returns no sensitive details."""
    try:
        await _database(ctx).health_check()
        return HealthResult(ok=True, status="ready", database_available=True)
    except Exception as exc:
        logger.warning("Database health check failed (%s)", type(exc).__name__)
        return HealthResult(
            ok=False,
            status="degraded",
            database_available=False,
            error=PublicError(
                code="database_unavailable", message="The database is currently unavailable."
            ),
        )
