"""Strict contracts shared by the read-only financial domain tools."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from supabase_mcp.models import StrictModel, UserScope


class TimePeriod(StrEnum):
    TODAY = "today"
    CURRENT_WEEK = "current_week"
    CURRENT_MONTH = "current_month"
    PREVIOUS_MONTH = "previous_month"
    LAST_30_DAYS = "last_30_days"
    LAST_90_DAYS = "last_90_days"
    LAST_3_MONTHS = "last_3_months"
    LAST_6_MONTHS = "last_6_months"
    LAST_12_MONTHS = "last_12_months"
    CURRENT_YEAR = "current_year"
    CUSTOM = "custom"


class ResolvedDateRange(StrictModel):
    start_date: date
    end_date: date
    end_inclusive: Literal[True] = True
    timezone: str


class Pagination(StrictModel):
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=256)


class MoneyAmount(StrictModel):
    currency: str = Field(min_length=3, max_length=3)
    amount: Decimal


class CurrencyTotal(StrictModel):
    currency: str = Field(min_length=3, max_length=3)
    total: Decimal


class AppliedFilters(StrictModel):
    period: ResolvedDateRange | None = None
    account_ids: list[UUID] = Field(default_factory=list, max_length=50)


class DataQuality(StrictModel):
    complete: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=20)


AccountIds = Annotated[list[UUID], Field(max_length=50)]
ResourceIds = Annotated[list[UUID], Field(max_length=100)]


class _ScopedRequest(StrictModel):
    scope: UserScope = Field(description="Trusted user scope / Ámbito de usuario confiable")


class _PeriodRequest(_ScopedRequest):
    period: TimePeriod = TimePeriod.CURRENT_MONTH
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_custom_dates(self) -> Self:
        if self.period is TimePeriod.CUSTOM:
            if self.start_date is None or self.end_date is None:
                raise ValueError("custom / personalizado requires start_date and end_date")
            if self.end_date < self.start_date:
                raise ValueError("end_date must be on or after start_date")
        elif self.start_date is not None or self.end_date is not None:
            raise ValueError("start_date and end_date are only valid for custom / personalizado")
        return self


class FinancialOverviewRequest(_ScopedRequest):
    period: Literal["current_month", "previous_month", "last_30_days", "current_year"] = (
        "current_month"
    )
    account_ids: AccountIds = Field(default_factory=list)


class AccountsRequest(_ScopedRequest):
    account_ids: AccountIds = Field(default_factory=list)
    account_type: str | None = Field(default=None, max_length=50)
    include_cards: bool = True
    include_credit_terms: bool = True
    status: str | None = Field(default=None, max_length=50)


class TransactionsRequest(_PeriodRequest, Pagination):
    period: Literal[
        "today",
        "current_week",
        "current_month",
        "previous_month",
        "last_30_days",
        "last_90_days",
        "current_year",
        "custom",
    ] = "current_month"
    direction: Literal["income", "expense"] | None = None
    account_ids: AccountIds = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list, max_length=30)
    merchant_query: str | None = Field(default=None, min_length=1, max_length=100)
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    order: Literal["newest", "oldest", "highest", "lowest"] = "newest"

    @model_validator(mode="after")
    def validate_amounts(self) -> Self:
        if self.min_amount is not None and self.max_amount is not None:
            if self.max_amount < self.min_amount:
                raise ValueError("max_amount must be greater than or equal to min_amount")
        return self


class SpendingAnalysisRequest(_PeriodRequest):
    period: Literal[
        "today",
        "current_week",
        "current_month",
        "previous_month",
        "last_30_days",
        "last_90_days",
        "current_year",
        "custom",
    ] = "current_month"
    account_ids: AccountIds = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list, max_length=30)
    compare_with_previous_period: bool = True
    include_daily_series: bool = True
    include_top_merchants: bool = True
    top_merchants_limit: int = Field(default=10, ge=1, le=25)


class CashFlowRequest(_PeriodRequest):
    period: Literal[
        "last_3_months", "last_6_months", "last_12_months", "current_year", "custom"
    ] = "last_6_months"
    account_ids: AccountIds = Field(default_factory=list)


class BudgetProgressRequest(_ScopedRequest):
    budget_ids: ResourceIds = Field(default_factory=list)
    status: Literal["active", "completed", "all"] = "active"
    category: str | None = Field(default=None, max_length=100)
    account_ids: AccountIds = Field(default_factory=list)
    include_expired: bool = False


class SavingsProgressRequest(_ScopedRequest):
    goal_ids: ResourceIds = Field(default_factory=list)
    status: Literal["active", "completed", "all"] = "active"
    account_ids: AccountIds = Field(default_factory=list)
    include_contributions: bool = False
    contributions_limit: int = Field(default=20, ge=1, le=100)


class DebtOverviewRequest(_ScopedRequest):
    debt_ids: ResourceIds = Field(default_factory=list)
    account_ids: AccountIds = Field(default_factory=list)
    status: Literal["active", "paid", "all"] = "active"
    include_credit_cards: bool = True
    include_scenarios: bool = True


class UpcomingPaymentsRequest(_ScopedRequest):
    days_ahead: int = Field(default=30, ge=1, le=365)
    account_ids: AccountIds = Field(default_factory=list)
    include_expected_income: bool = False
    include_drafts: bool = False


class FinancialAlertsRequest(_ScopedRequest, Pagination):
    status: Literal["active", "dismissed", "all"] = "active"
    kinds: list[str] = Field(default_factory=list, max_length=20)
    account_ids: AccountIds = Field(default_factory=list)
    budget_ids: ResourceIds = Field(default_factory=list)
    due_within_days: int | None = Field(default=None, ge=0, le=365)


class BankStatementsRequest(_ScopedRequest, Pagination):
    account_ids: AccountIds = Field(default_factory=list)
    period_start: date | None = None
    period_end: date | None = None
    document_status: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        return self


class PaymentActivityRequest(_PeriodRequest, Pagination):
    account_ids: AccountIds = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list, max_length=20)
    statuses: list[str] = Field(default_factory=list, max_length=20)


class BeneficiariesRequest(_ScopedRequest, Pagination):
    status: str | None = Field(default=None, max_length=50)
    query: str | None = Field(default=None, min_length=1, max_length=100)


class TransactionDisputesRequest(_ScopedRequest, Pagination):
    statuses: list[str] = Field(default_factory=list, max_length=20)
    transaction_ids: ResourceIds = Field(default_factory=list)
    account_ids: AccountIds = Field(default_factory=list)
    period: TimePeriod | None = None


class CompareDebtScenariosRequest(_ScopedRequest):
    debt_id: UUID
    scenario_ids: ResourceIds = Field(default_factory=list)
    order_by: Literal["lowest_total_interest", "lowest_monthly_payment", "fastest_payoff"] = (
        "lowest_total_interest"
    )


__all__ = [
    name
    for name in globals()
    if name.endswith("Request")
    or name
    in {
        "AppliedFilters",
        "CurrencyTotal",
        "DataQuality",
        "MoneyAmount",
        "Pagination",
        "ResolvedDateRange",
        "TimePeriod",
    }
]
