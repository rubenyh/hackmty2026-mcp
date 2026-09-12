"""MCP tool handlers."""

from supabase_mcp.tools.a2ui import (
    a2ui_action,
    a2ui_error,
    database_overview,
    database_overview_resource,
)
from supabase_mcp.tools.health import health_check
from supabase_mcp.tools.schema import describe_table, list_allowed_tables
from supabase_mcp.tools.select import select_rows

__all__ = [
    "a2ui_action",
    "a2ui_error",
    "database_overview",
    "database_overview_resource",
    "describe_table",
    "health_check",
    "list_allowed_tables",
    "select_rows",
]
