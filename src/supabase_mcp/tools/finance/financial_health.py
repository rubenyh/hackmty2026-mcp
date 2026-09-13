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
    """Summarize the whole financial picture of the user in one call.

    Returns per currency the available balance, income, expenses, net,
    outstanding debt and savings totals for the period, plus active and
    over-limit budget counts, the next obligation date and how many alerts are
    active. Use it for broad questions about overall finances or financial
    health. It answers with totals and counts, so a narrow question belongs to
    the narrow tool that returns the underlying rows.
    """
    return await _run("get_financial_overview", request, ctx, get_financial_overview_data)


async def get_financial_alerts(request: FinancialAlertsRequest, ctx: Context) -> ToolResult:
    """List the financial alerts and warnings already raised for the user.

    Returns each alert with its kind, title, message, threshold amount, due
    date and status, covering overdraft risk, budget overruns, unusual charges
    and urgent dates, filtered by kind, account, budget, status and how soon it
    is due. Use it when the user asks whether anything needs attention. It
    reads stored alerts and derives none: budget detail belongs to
    get_budget_progress and due dates to get_upcoming_payments.
    """
    return await _run("get_financial_alerts", request, ctx, get_financial_alerts_data)


__all__ = ["get_financial_alerts", "get_financial_overview"]
