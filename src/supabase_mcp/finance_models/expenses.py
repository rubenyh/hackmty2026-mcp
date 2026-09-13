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
    direction: Literal["income", "expense"] | None = Field(
        default=None,
        description="Keep only money coming in or only money going out; omit for both.",
    )
    account_ids: AccountIds = Field(
        default_factory=list, description="Restrict to these account ids; empty means all accounts."
    )
    categories: list[str] = Field(
        default_factory=list,
        max_length=30,
        description="Restrict to these spending categories, such as groceries or transport.",
    )
    merchant_query: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Case-insensitive fragment of the merchant name to match.",
    )
    min_amount: Decimal | None = Field(
        default=None, ge=0, description="Keep only transactions of at least this amount."
    )
    max_amount: Decimal | None = Field(
        default=None, ge=0, description="Keep only transactions of at most this amount."
    )
    order: Literal["newest", "oldest", "highest", "lowest"] = Field(
        default="newest",
        description="Sort newest or oldest by date, or highest or lowest by amount.",
    )

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
    account_ids: AccountIds = Field(
        default_factory=list, description="Restrict to these account ids; empty means all accounts."
    )
    categories: list[str] = Field(
        default_factory=list,
        max_length=30,
        description="Restrict the analysis to these spending categories.",
    )
    compare_with_previous_period: bool = Field(
        default=True,
        description="Also total the preceding period of the same length for comparison.",
    )
    include_daily_series: bool = Field(
        default=True, description="Include the day-by-day spending series for the period."
    )
    include_top_merchants: bool = Field(
        default=True, description="Include the merchants with the highest spending."
    )
    top_merchants_limit: int = Field(
        default=10, ge=1, le=25, description="How many top merchants to return."
    )


class TransactionDisputesRequest(_ScopedRequest, Pagination):
    statuses: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Restrict to disputes in these statuses, such as open or resolved.",
    )
    transaction_ids: ResourceIds = Field(
        default_factory=list,
        description="Restrict to disputes over these transaction ids, as returned by "
        "get_transactions.",
    )
    account_ids: AccountIds = Field(
        default_factory=list, description="Restrict to these account ids; empty means all accounts."
    )
    period: TimePeriod | None = Field(
        default=None, description="Keep only disputes opened inside this named date range."
    )


__all__ = ["SpendingAnalysisRequest", "TransactionDisputesRequest", "TransactionsRequest"]
