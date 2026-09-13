"""Public financial MCP tools and explicit registration collection."""

from supabase_mcp.tools.finance.accounts import get_accounts, get_bank_statements
from supabase_mcp.tools.finance.budgets import get_budget_progress
from supabase_mcp.tools.finance.cash_flow import get_cash_flow
from supabase_mcp.tools.finance.debts import compare_debt_scenarios, get_debt_overview
from supabase_mcp.tools.finance.expenses import (
    analyze_spending,
    get_transaction_disputes,
    get_transactions,
)
from supabase_mcp.tools.finance.financial_health import (
    get_financial_alerts,
    get_financial_overview,
)
from supabase_mcp.tools.finance.payments import (
    get_beneficiaries,
    get_payment_activity,
    get_upcoming_payments,
)
from supabase_mcp.tools.finance.savings import get_savings_progress

FINANCIAL_TOOLS = (
    get_financial_overview,
    get_accounts,
    get_transactions,
    analyze_spending,
    get_cash_flow,
    get_budget_progress,
    get_savings_progress,
    get_debt_overview,
    get_upcoming_payments,
    get_financial_alerts,
    get_bank_statements,
    get_payment_activity,
    get_beneficiaries,
    get_transaction_disputes,
    compare_debt_scenarios,
)

__all__ = [
    "FINANCIAL_TOOLS",
    "analyze_spending",
    "compare_debt_scenarios",
    "get_accounts",
    "get_bank_statements",
    "get_beneficiaries",
    "get_budget_progress",
    "get_cash_flow",
    "get_debt_overview",
    "get_financial_alerts",
    "get_financial_overview",
    "get_payment_activity",
    "get_savings_progress",
    "get_transaction_disputes",
    "get_transactions",
    "get_upcoming_payments",
]
