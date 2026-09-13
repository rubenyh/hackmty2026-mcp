"""Savings-progress MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.savings import SavingsProgressRequest
from supabase_mcp.services.finance.savings import get_savings_progress_data
from supabase_mcp.tools.finance._shared import _run


async def get_savings_progress(request: SavingsProgressRequest, ctx: Context) -> ToolResult:
    """Avance de metas de ahorro / Savings-goal progress.

    Use for target, saved, remaining, percentage, target date, suggested
    contribution, and optional contributions. Úsala para metas de ahorro.
    """
    return await _run("get_savings_progress", request, ctx, get_savings_progress_data)


__all__ = ["get_savings_progress"]
