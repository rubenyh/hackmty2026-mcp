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
    """Summarize the outstanding debts the user owes, cards included.

    Returns per debt the outstanding principal, interest rate, monthly payment
    and next due date; per credit card the limit, current debt, statement
    balance, minimum payment, cutoff, due date and utilization; totals owed by
    currency; and optionally the payoff scenarios stored for each debt. Use it
    when the user asks how much they owe. Ranking those scenarios against each
    other belongs to compare_debt_scenarios, and a minimum payment is a
    contractual amount rather than advice.
    """
    return await _run("get_debt_overview", request, ctx, get_debt_overview_data)


async def compare_debt_scenarios(request: CompareDebtScenariosRequest, ctx: Context) -> ToolResult:
    """Rank the stored payoff projections of one debt against each other.

    Returns the saved scenarios of a single debt with their monthly payment,
    extra payment, projected months to payoff, projected total interest and
    total paid, the assumptions behind each projection, and the difference of
    every scenario against the baseline, ordered by lowest total interest,
    lowest monthly payment or fastest payoff. Use it when the user compares
    payoff strategies such as paying extra each month. It needs a debt id from
    get_debt_overview, computes no new projection and saves nothing.
    """
    return await _run("compare_debt_scenarios", request, ctx, compare_debt_scenarios_data)


__all__ = ["compare_debt_scenarios", "get_debt_overview"]
