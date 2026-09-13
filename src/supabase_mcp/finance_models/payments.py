"""Upcoming and historical payment request contracts."""

from __future__ import annotations

from pydantic import Field

from supabase_mcp.finance_models._shared import (
    AccountIds,
    Pagination,
    _PeriodRequest,
    _ScopedRequest,
)


class UpcomingPaymentsRequest(_ScopedRequest):
    days_ahead: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Size of the forward window in days / Dias hacia adelante",
    )
    account_ids: AccountIds = Field(default_factory=list)
    include_expected_income: bool = False
    include_drafts: bool = False


class PaymentActivityRequest(_PeriodRequest, Pagination):
    account_ids: AccountIds = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list, max_length=20)
    statuses: list[str] = Field(default_factory=list, max_length=20)


class BeneficiariesRequest(_ScopedRequest, Pagination):
    status: str | None = Field(default=None, max_length=50)
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Name or bank fragment to match / Fragmento de nombre o banco",
    )


__all__ = ["BeneficiariesRequest", "PaymentActivityRequest", "UpcomingPaymentsRequest"]
