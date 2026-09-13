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
    """Movimientos y compras individuales / Individual transaction records.

    Raw transaction rows filtered by account, date range, category, merchant,
    amount and direction. Records, not aggregates: category totals belong to
    analyze_spending. Claves: movimiento, movimientos, compra, compras, cargo,
    cargos, ultimos movimientos, transaction, transactions, purchases, charges.
    """
    return await _run("get_transactions", request, ctx, get_transactions_data)


async def analyze_spending(request: SpendingAnalysisRequest, ctx: Context) -> ToolResult:
    """Analisis de gastos agregados / Aggregated spending analysis.

    Totals spent by category, daily series, top merchants and comparison
    against the prior period. Reads the underlying rows itself, so a
    get_transactions call beforehand stays redundant. Claves: gasto, gastos,
    gaste, cuanto gaste este mes, en que gasto, spend, spent, spending,
    spending this month, expenses, spending by category, top merchants.
    """
    return await _run("analyze_spending", request, ctx, analyze_spending_data)


async def get_transaction_disputes(request: TransactionDisputesRequest, ctx: Context) -> ToolResult:
    """Aclaraciones y cargos no reconocidos / Transaction disputes.

    Dispute status, reason, opened date and a safe summary of the disputed
    transaction. Identifiers are validated against the authenticated user.
    Claves: aclaracion, aclaraciones, cargo no reconocido, reclamacion,
    fraude, dispute, disputes, disputed charge, unrecognized charge,
    chargeback, fraud.
    """
    return await _run("get_transaction_disputes", request, ctx, get_transaction_disputes_data)


__all__ = ["analyze_spending", "get_transaction_disputes", "get_transactions"]
