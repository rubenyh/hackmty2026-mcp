"""Financial overview and alert MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.financial_health import (
    FinancialAlertsRequest,
    FinancialOverviewRequest,
)
from supabase_mcp.services.finance.financial_health import (
    get_financial_alerts_data,
    get_financial_overview_data,
)
from supabase_mcp.tools.finance._shared import _run


async def get_financial_overview(request: FinancialOverviewRequest, ctx: Context) -> ToolResult:
    """Resumen financiero general / General financial overview.

    Use for broad health, monthly summary, balances, budgets, savings, debts,
    obligations, and alerts in one call; do not manually combine narrower tools.
    Úsala para panorama general, resumen mensual o señales preocupantes.
    """
    return await _run("get_financial_overview", request, ctx, get_financial_overview_data)


async def get_financial_alerts(request: FinancialAlertsRequest, ctx: Context) -> ToolResult:
    """Alertas financieras / Financial alerts.

    Use for warnings filtered by kind, account, budget, urgency, and due date.
    Úsala para avisos, riesgos y señales urgentes.
    """
    return await _run("get_financial_alerts", request, ctx, get_financial_alerts_data)


__all__ = ["get_financial_alerts", "get_financial_overview"]
