"""Typed access to process-scoped tool dependencies."""

from __future__ import annotations

from fastmcp import Context

from supabase_mcp.database import DatabaseClient


def database_from_context(ctx: Context) -> DatabaseClient:
    """Return the lifespan-managed database client or fail closed."""
    database = ctx.lifespan_context.get("database")
    if not isinstance(database, DatabaseClient):
        raise RuntimeError("database lifespan context is unavailable")
    return database
