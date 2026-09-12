"""MCP tool handlers."""

from supabase_mcp.tools.a2ui import (
    a2ui_action,
    a2ui_error,
    chat_message,
    chat_message_resource,
    data_chart_resource,
    database_overview,
    database_overview_resource,
    financial_view_resource,
    present_financial_view,
    visualize_allowed_data,
)
from supabase_mcp.tools.health import health_check
from supabase_mcp.tools.schema import describe_table, list_allowed_tables
from supabase_mcp.tools.select import select_rows

__all__ = [
    "a2ui_action",
    "a2ui_error",
    "chat_message",
    "chat_message_resource",
    "data_chart_resource",
    "database_overview",
    "database_overview_resource",
    "describe_table",
    "financial_view_resource",
    "health_check",
    "list_allowed_tables",
    "present_financial_view",
    "select_rows",
    "visualize_allowed_data",
]
