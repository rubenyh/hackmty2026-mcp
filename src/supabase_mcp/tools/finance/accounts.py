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
    """Read the user's bank accounts with balances, cards and credit terms.

    Returns one row per account: name, type, currency, available and current
    balance, how much money is available right now, masked card metadata and
    current credit-card terms. Use it for account and balance questions.
    Individual movements belong to get_transactions and statement documents to
    get_bank_statements. CLABE and full card numbers are never returned.
    """
    return await _run("get_accounts", request, ctx, get_accounts_data)


async def get_bank_statements(request: BankStatementsRequest, ctx: Context) -> ToolResult:
    """List the issued bank statement documents of the user's accounts.

    Returns one row per monthly statement: statement period, opening and
    closing balance, issue date and availability, paginated. Use it when the
    user asks for a statement document or a past monthly cutoff. Today's
    balances belong to get_accounts and individual movements to
    get_transactions. Storage paths and download links are never returned.
    """
    return await _run("get_bank_statements", request, ctx, get_bank_statements_data)


__all__ = ["get_accounts", "get_bank_statements"]
