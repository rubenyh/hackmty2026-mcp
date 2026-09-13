"""Public financial request and value contracts."""

from supabase_mcp.finance_models._shared import (
    AppliedFilters,
    CurrencyTotal,
    DataQuality,
    MoneyAmount,
    Pagination,
    ResolvedDateRange,
    TimePeriod,
)
from supabase_mcp.finance_models.accounts import AccountsRequest, BankStatementsRequest
from supabase_mcp.finance_models.budgets import BudgetProgressRequest
from supabase_mcp.finance_models.cash_flow import CashFlowRequest
from supabase_mcp.finance_models.debts import CompareDebtScenariosRequest, DebtOverviewRequest
from supabase_mcp.finance_models.expenses import (
    SpendingAnalysisRequest,
    TransactionDisputesRequest,
    TransactionsRequest,
)
from supabase_mcp.finance_models.financial_health import (
    FinancialAlertsRequest,
    FinancialOverviewRequest,
)
from supabase_mcp.finance_models.payments import (
    BeneficiariesRequest,
    PaymentActivityRequest,
    UpcomingPaymentsRequest,
)
from supabase_mcp.finance_models.predictions import (
    DetectTransactionAnomaliesRequest,
    ForecastCashBalanceRequest,
    ForecastRecurringChargesRequest,
    PredictSavingsGoalRequest,
)
from supabase_mcp.finance_models.savings import SavingsProgressRequest

__all__ = [
    "AccountsRequest",
    "AppliedFilters",
    "BankStatementsRequest",
    "BeneficiariesRequest",
    "BudgetProgressRequest",
    "CashFlowRequest",
    "CompareDebtScenariosRequest",
    "CurrencyTotal",
    "DataQuality",
    "DebtOverviewRequest",
    "DetectTransactionAnomaliesRequest",
    "FinancialAlertsRequest",
    "FinancialOverviewRequest",
    "ForecastCashBalanceRequest",
    "ForecastRecurringChargesRequest",
    "MoneyAmount",
    "Pagination",
    "PaymentActivityRequest",
    "PredictSavingsGoalRequest",
    "ResolvedDateRange",
    "SavingsProgressRequest",
    "SpendingAnalysisRequest",
    "TimePeriod",
    "TransactionDisputesRequest",
    "TransactionsRequest",
    "UpcomingPaymentsRequest",
]
