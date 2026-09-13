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
    """Resumen financiero general / Whole-picture financial overview.

    Balances, budgets, savings goals, debts, upcoming obligations and alerts in
    a single call. Covers the broad question; a narrow question belongs to the
    narrow tool. Claves: resumen, panorama, panorama financiero, salud
    financiera, finanzas en general, overall summary, financial health.
    """
    return await _run("get_financial_overview", request, ctx, get_financial_overview_data)


async def get_financial_alerts(request: FinancialAlertsRequest, ctx: Context) -> ToolResult:
    """Alertas y avisos financieros / Financial alerts and warnings.

    Warnings filtered by kind, account, budget, urgency and due date:
    overdraft risk, budget overruns, unusual charges and urgent dates. Claves:
    alerta, alertas, aviso, avisos, advertencia, advertencias, riesgo, urgente,
    alert, alerts, warning, warnings, risks.
    """
    return await _run("get_financial_alerts", request, ctx, get_financial_alerts_data)


__all__ = ["get_financial_alerts", "get_financial_overview"]
