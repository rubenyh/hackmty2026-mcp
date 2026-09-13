"""Account and bank-statement MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.accounts import (
    AccountsRequest,
    BankStatementsRequest,
    CreditCardsRequest,
)
from supabase_mcp.services.finance.accounts import (
    get_accounts_data,
    get_bank_statements_data,
    get_credit_cards_data,
)
from supabase_mcp.tools.finance._shared import _run


async def get_accounts(request: AccountsRequest, ctx: Context) -> ToolResult:
    """Cuentas, saldos y tarjetas / Accounts, balances and cards.

    Account names, available and current balances, masked card metadata and
    current credit terms. Excludes CLABE and full card numbers. Movements
    belong to get_transactions, documents to get_bank_statements. Claves:
    cuenta, cuentas, saldo, saldos, tarjeta, tarjetas, dinero disponible,
    account, accounts, balance, balances, cards, available money.
    """
    return await _run("get_accounts", request, ctx, get_accounts_data)


async def get_credit_cards(request: CreditCardsRequest, ctx: Context) -> ToolResult:
    """Tarjetas de crédito del usuario / User credit cards.

    Active, blocked or inactive credit cards with masked last four digits,
    available credit and current payment terms. Excludes debit cards, full card
    numbers and unrelated account details. Claves: tarjeta de crédito, mi
    tarjeta, crédito disponible, pago mínimo, fecha límite, credit card,
    available credit, minimum payment, due date.
    """
    return await _run("get_credit_cards", request, ctx, get_credit_cards_data)


async def get_bank_statements(request: BankStatementsRequest, ctx: Context) -> ToolResult:
    """Estados de cuenta / Bank statement documents.

    Statement period, opening and closing balance, issue date and availability
    metadata. Excludes storage paths, CLABE and invented URLs. Current
    balances belong to get_accounts, movements to get_transactions. Claves:
    estado de cuenta, estados de cuenta, corte, documento, bank statement,
    bank statements, statement, statements, monthly statement.
    """
    return await _run("get_bank_statements", request, ctx, get_bank_statements_data)


__all__ = ["get_accounts", "get_bank_statements", "get_credit_cards"]
