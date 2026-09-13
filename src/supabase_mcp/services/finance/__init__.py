"""Public financial domain services.

This package preserves the former supabase_mcp.services.finance import path
while implementations live in cohesive domain modules.
"""

from supabase_mcp.services.finance._shared import resolve_period
from supabase_mcp.services.finance.accounts import (
    get_accounts_data,
    get_bank_statements_data,
)
from supabase_mcp.services.finance.budgets import get_budget_progress_data
from supabase_mcp.services.finance.cash_flow import get_cash_flow_data
from supabase_mcp.services.finance.debts import (
    compare_debt_scenarios_data,
    get_debt_overview_data,
)
from supabase_mcp.services.finance.expenses import (
    analyze_spending_data,
    get_transaction_disputes_data,
    get_transactions_data,
)
from supabase_mcp.services.finance.financial_health import (
    get_financial_alerts_data,
    get_financial_overview_data,
)
from supabase_mcp.services.finance.payments import (
    get_beneficiaries_data,
    get_payment_activity_data,
    get_upcoming_payments_data,
)
from supabase_mcp.services.finance.predictions import PredictionService
from supabase_mcp.services.finance.savings import get_savings_progress_data

__all__ = [
    "PredictionService",
    "analyze_spending_data",
    "compare_debt_scenarios_data",
    "get_accounts_data",
    "get_bank_statements_data",
    "get_beneficiaries_data",
    "get_budget_progress_data",
    "get_cash_flow_data",
    "get_debt_overview_data",
    "get_financial_alerts_data",
    "get_financial_overview_data",
    "get_payment_activity_data",
    "get_savings_progress_data",
    "get_transaction_disputes_data",
    "get_transactions_data",
    "get_upcoming_payments_data",
    "resolve_period",
]
