"""Cash-flow MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.cash_flow import CashFlowRequest
from supabase_mcp.services.finance.cash_flow import get_cash_flow_data
from supabase_mcp.tools.finance._shared import _run


async def get_cash_flow(request: CashFlowRequest, ctx: Context) -> ToolResult:
    """Ingresos contra gastos en el tiempo / Income versus expenses over time.

    Use for 3, 6, or 12-month cash-flow trends; for categories use
    analyze_spending. Úsala para comparar ingresos, gastos y neto por mes.
    """
    return await _run("get_cash_flow", request, ctx, get_cash_flow_data)


__all__ = ["get_cash_flow"]
