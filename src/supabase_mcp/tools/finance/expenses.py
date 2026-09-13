"""Transaction, spending-analysis, and dispute MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.expenses import (
    SpendingAnalysisRequest,
    TransactionDisputesRequest,
    TransactionsRequest,
)
from supabase_mcp.services.finance.expenses import (
    analyze_spending_data,
    get_transaction_disputes_data,
    get_transactions_data,
)
from supabase_mcp.tools.finance._shared import _run


async def get_transactions(request: TransactionsRequest, ctx: Context) -> ToolResult:
    """List the individual transactions of the user's accounts.

    Returns the latest transaction records with date, amount, direction,
    category, merchant and account, filtered by account, period, category,
    merchant fragment, amount range and direction, ordered by date or amount
    and paginated. Use it when the user wants the purchases or charges
    themselves. Totals by category, a daily series or top merchants belong to
    analyze_spending instead of adding these rows up.
    """
    return await _run("get_transactions", request, ctx, get_transactions_data)


async def analyze_spending(request: SpendingAnalysisRequest, ctx: Context) -> ToolResult:
    """Aggregate how much the user spends in a period and on what.

    Returns expenses per currency, spending by category, an optional daily
    series, the top merchants, and an optional comparison against the
    immediately preceding period of the same length. Use it when the user asks
    how much they spend, how much they spent this month, or where their money
    goes. It reads the underlying transactions itself, so calling
    get_transactions first is redundant; that tool returns the individual rows.
    """
    return await _run("analyze_spending", request, ctx, analyze_spending_data)


async def get_transaction_disputes(request: TransactionDisputesRequest, ctx: Context) -> ToolResult:
    """List disputes opened over charges the user did not recognize.

    Returns each dispute with its status, reason, resolution and opened date,
    plus a safe summary of the disputed transaction, filtered by status,
    transaction, account and period. Use it when the user reports an
    unrecognized or fraudulent charge, a chargeback or an existing claim. It
    reports disputes and opens none; the charge itself belongs to
    get_transactions.
    """
    return await _run("get_transaction_disputes", request, ctx, get_transaction_disputes_data)


__all__ = ["analyze_spending", "get_transaction_disputes", "get_transactions"]
