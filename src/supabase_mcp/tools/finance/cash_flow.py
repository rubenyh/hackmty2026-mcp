"""Cash-flow MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.cash_flow import CashFlowRequest
from supabase_mcp.services.finance.cash_flow import get_cash_flow_data
from supabase_mcp.tools.finance._shared import _run


async def get_cash_flow(request: CashFlowRequest, ctx: Context) -> ToolResult:
    """Flujo de efectivo mensual / Monthly cash flow.

    Income against expenses and the resulting net per calendar month, across a
    3, 6 or 12 month window. Trend over time; a category breakdown inside one
    period belongs to analyze_spending. Claves: flujo, flujo de efectivo,
    ingresos, egresos, ingresos contra gastos, cash flow, income versus
    expenses, monthly trend.
    """
    return await _run("get_cash_flow", request, ctx, get_cash_flow_data)


__all__ = ["get_cash_flow"]
