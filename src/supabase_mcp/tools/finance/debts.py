"""Debt-overview and scenario-comparison MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.debts import CompareDebtScenariosRequest, DebtOverviewRequest
from supabase_mcp.services.finance.debts import (
    compare_debt_scenarios_data,
    get_debt_overview_data,
)
from supabase_mcp.tools.finance._shared import _run


async def get_debt_overview(request: DebtOverviewRequest, ctx: Context) -> ToolResult:
    """Panorama de deudas y tarjetas / Debt and credit-card overview.

    Use for amounts owed, rates, due dates, utilization, and related scenarios;
    for ranking scenarios use compare_debt_scenarios. El mínimo no es recomendación.
    """
    return await _run("get_debt_overview", request, ctx, get_debt_overview_data)


async def compare_debt_scenarios(request: CompareDebtScenariosRequest, ctx: Context) -> ToolResult:
    """Compara escenarios de deuda / Compare saved debt scenarios.

    Ranks existing scenarios and shows baseline differences; never invents or
    persists scenarios. Úsala solo para comparar escenarios existentes.
    """
    return await _run("compare_debt_scenarios", request, ctx, compare_debt_scenarios_data)


__all__ = ["compare_debt_scenarios", "get_debt_overview"]
