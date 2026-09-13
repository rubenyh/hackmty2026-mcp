"""Cash-flow MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.cash_flow import CashFlowRequest
from supabase_mcp.services.finance.cash_flow import get_cash_flow_data
from supabase_mcp.tools.finance._shared import _run


async def get_cash_flow(request: CashFlowRequest, ctx: Context) -> ToolResult:
    """Compare income against expenses for each calendar month.

    Returns a monthly cash flow series of income, expenses and net per
    currency across a window of 3, 6 or 12 months, plus the totals for that
    window. Use it for the trend of money coming in versus money going out
    over time. A category breakdown inside one period belongs to
    analyze_spending, and charges still ahead to get_upcoming_payments.
    """
    return await _run("get_cash_flow", request, ctx, get_cash_flow_data)


__all__ = ["get_cash_flow"]
