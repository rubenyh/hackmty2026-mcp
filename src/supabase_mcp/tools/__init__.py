"""MCP tool handlers."""

from supabase_mcp.tools.health import health_check
from supabase_mcp.tools.schema import describe_table, list_allowed_tables
from supabase_mcp.tools.select import select_rows

__all__ = ["describe_table", "health_check", "list_allowed_tables", "select_rows"]
