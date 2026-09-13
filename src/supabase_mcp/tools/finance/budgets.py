"""Budget-progress MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.budgets import BudgetProgressRequest
from supabase_mcp.services.finance.budgets import get_budget_progress_data
from supabase_mcp.tools.finance._shared import _run


async def get_budget_progress(request: BudgetProgressRequest, ctx: Context) -> ToolResult:
    """Report how each budget is doing against its limit.

    Returns per budget the limit, amount spent, remaining amount, percentage
    used, period dates and status, already calculated by the database. Use it
    when the user asks about a budget, what is left of it, or whether it is
    over its limit. It reports budgets and never re-derives spending from
    transactions; category spending itself belongs to analyze_spending.
    """
    return await _run("get_budget_progress", request, ctx, get_budget_progress_data)


__all__ = ["get_budget_progress"]
