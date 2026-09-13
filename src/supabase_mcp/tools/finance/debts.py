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
    """Deudas y tarjetas de credito / Debts and credit-card balances owed.

    Amounts owed, outstanding balances, interest rates, minimum payments, due
    dates, credit utilization and the payoff scenarios stored against each
    debt. Ranking scenarios belongs to compare_debt_scenarios, and a minimum
    payment is data rather than advice. Claves: deuda, deudas, deudas
    pendientes, debo, cuanto debo, debt, debts, outstanding debt, owed, credit
    card debt, credit card balance.
    """
    return await _run("get_debt_overview", request, ctx, get_debt_overview_data)


async def compare_debt_scenarios(request: CompareDebtScenariosRequest, ctx: Context) -> ToolResult:
    """Compara escenarios de pago de deuda / Compare saved debt payoff scenarios.

    Ranks the scenarios already stored against one debt by total interest,
    monthly payment or payoff speed, against the baseline. Invents and persists
    nothing, and needs a debt id produced by get_debt_overview. Claves:
    comparar, compara, comparacion, escenario, escenarios, estrategia,
    avalancha, bola de nieve, compare scenarios, payoff strategies, snowball,
    avalanche.
    """
    return await _run("compare_debt_scenarios", request, ctx, compare_debt_scenarios_data)


__all__ = ["compare_debt_scenarios", "get_debt_overview"]
