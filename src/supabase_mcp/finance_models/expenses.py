"""Transaction, spending, and dispute request contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from supabase_mcp.finance_models._shared import (
    AccountIds,
    Pagination,
    ResourceIds,
    TimePeriod,
    _PeriodRequest,
    _ScopedRequest,
)


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
    ] = "current_month"  # type: ignore[assignment]
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
    ] = "current_month"  # type: ignore[assignment]
    account_ids: AccountIds = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list, max_length=30)
    compare_with_previous_period: bool = True
    include_daily_series: bool = True
    include_top_merchants: bool = True
    top_merchants_limit: int = Field(default=10, ge=1, le=25)


class TransactionDisputesRequest(_ScopedRequest, Pagination):
    statuses: list[str] = Field(default_factory=list, max_length=20)
    transaction_ids: ResourceIds = Field(default_factory=list)
    account_ids: AccountIds = Field(default_factory=list)
    period: TimePeriod | None = None


__all__ = ["SpendingAnalysisRequest", "TransactionDisputesRequest", "TransactionsRequest"]
