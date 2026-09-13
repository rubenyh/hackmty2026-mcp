"""Savings-progress MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.savings import SavingsProgressRequest
from supabase_mcp.services.finance.savings import get_savings_progress_data
from supabase_mcp.tools.finance._shared import _run


async def get_savings_progress(request: SavingsProgressRequest, ctx: Context) -> ToolResult:
    """Report progress toward each savings goal.

    Returns per goal the target amount, amount saved, remaining amount,
    percentage complete, target date and suggested monthly contribution, with
    optional contribution history. Use it for savings and goal progress
    questions. Budget limits belong to get_budget_progress and account
    balances to get_accounts.
    """
    return await _run("get_savings_progress", request, ctx, get_savings_progress_data)


__all__ = ["get_savings_progress"]
