"""Account and bank-statement MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.accounts import AccountsRequest, BankStatementsRequest
from supabase_mcp.services.finance.accounts import (
    get_accounts_data,
    get_bank_statements_data,
)
from supabase_mcp.tools.finance._shared import _run


async def get_accounts(request: AccountsRequest, ctx: Context) -> ToolResult:
    """Cuentas y tarjetas / Accounts and cards.

    Use for balances, safe account names, cards, and latest credit terms; never
    returns CLABE or full card numbers. Úsala para saldos y tarjetas.
    """
    return await _run("get_accounts", request, ctx, get_accounts_data)


async def get_bank_statements(request: BankStatementsRequest, ctx: Context) -> ToolResult:
    """Estados de cuenta / Bank statements.

    Returns safe metadata and availability; never exposes storage paths, CLABE,
    or invented URLs. Úsala para periodos y saldos de apertura/cierre.
    """
    return await _run("get_bank_statements", request, ctx, get_bank_statements_data)


__all__ = ["get_accounts", "get_bank_statements"]
