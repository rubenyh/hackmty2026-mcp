"""Public financial MCP tools and explicit registration collection."""

from pydantic import BaseModel

from supabase_mcp.finance_models import (
    AccountsRequest,
    BankStatementsRequest,
    BeneficiariesRequest,
    BudgetProgressRequest,
    CashFlowRequest,
    CompareDebtScenariosRequest,
    DebtOverviewRequest,
    DetectTransactionAnomaliesRequest,
    FinancialAlertsRequest,
    FinancialOverviewRequest,
    ForecastCashBalanceRequest,
    ForecastRecurringChargesRequest,
    PaymentActivityRequest,
    PredictSavingsGoalRequest,
    SavingsProgressRequest,
    SpendingAnalysisRequest,
    TransactionDisputesRequest,
    TransactionsRequest,
    UpcomingPaymentsRequest,
)
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
from supabase_mcp.tools.finance.predictions import (
    detect_transaction_anomalies,
    forecast_cash_balance,
    forecast_recurring_charges,
    predict_savings_goal,
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
    forecast_cash_balance,
    predict_savings_goal,
    forecast_recurring_charges,
    detect_transaction_anomalies,
)

FINANCIAL_REQUEST_MODELS: dict[str, type[BaseModel]] = {
    "get_financial_overview": FinancialOverviewRequest,
    "get_accounts": AccountsRequest,
    "get_transactions": TransactionsRequest,
    "analyze_spending": SpendingAnalysisRequest,
    "get_cash_flow": CashFlowRequest,
    "get_budget_progress": BudgetProgressRequest,
    "get_savings_progress": SavingsProgressRequest,
    "get_debt_overview": DebtOverviewRequest,
    "get_upcoming_payments": UpcomingPaymentsRequest,
    "get_financial_alerts": FinancialAlertsRequest,
    "get_bank_statements": BankStatementsRequest,
    "get_payment_activity": PaymentActivityRequest,
    "get_beneficiaries": BeneficiariesRequest,
    "get_transaction_disputes": TransactionDisputesRequest,
    "compare_debt_scenarios": CompareDebtScenariosRequest,
    "forecast_cash_balance": ForecastCashBalanceRequest,
    "predict_savings_goal": PredictSavingsGoalRequest,
    "forecast_recurring_charges": ForecastRecurringChargesRequest,
    "detect_transaction_anomalies": DetectTransactionAnomaliesRequest,
}

__all__ = [
    "FINANCIAL_REQUEST_MODELS",
    "FINANCIAL_TOOLS",
    "analyze_spending",
    "compare_debt_scenarios",
    "detect_transaction_anomalies",
    "forecast_cash_balance",
    "forecast_recurring_charges",
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
    "predict_savings_goal",
]
