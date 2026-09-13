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
    """Movimientos específicos / Specific transactions.

    Use for merchants, purchases, latest movements, or filtered lists; for
    aggregate patterns use analyze_spending. Úsala para movimientos concretos.
    """
    return await _run("get_transactions", request, ctx, get_transactions_data)


async def analyze_spending(request: SpendingAnalysisRequest, ctx: Context) -> ToolResult:
    """Patrones de gasto / Spending patterns.

    Use for categories, daily activity, top merchants, and previous-period
    comparison; do not call get_transactions first. Úsala para analizar gastos.
    """
    return await _run("analyze_spending", request, ctx, analyze_spending_data)


async def get_transaction_disputes(request: TransactionDisputesRequest, ctx: Context) -> ToolResult:
    """Aclaraciones de transacciones / Transaction disputes.

    Returns dispute status with a safe transaction summary and validates every
    identifier against the authenticated user. Úsala para cargos no reconocidos.
    """
    return await _run("get_transaction_disputes", request, ctx, get_transaction_disputes_data)


__all__ = ["analyze_spending", "get_transaction_disputes", "get_transactions"]
