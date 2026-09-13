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
        description="How many days ahead of today the window of due dates reaches.",
    )
    account_ids: AccountIds = Field(
        default_factory=list, description="Restrict to these account ids; empty means all accounts."
    )
    include_expected_income: bool = Field(
        default=False, description="Also include expected incoming money, not only charges due."
    )
    include_drafts: bool = Field(
        default=False, description="Also include payment orders still in draft status."
    )


class PaymentActivityRequest(_PeriodRequest, Pagination):
    account_ids: AccountIds = Field(
        default_factory=list,
        description="Restrict to money sent from these account ids; empty means all accounts.",
    )
    kinds: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Restrict to these activity kinds, such as transfer or payment_order.",
    )
    statuses: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Restrict to these statuses, such as completed, pending or failed.",
    )


class BeneficiariesRequest(_ScopedRequest, Pagination):
    status: str | None = Field(
        default=None, max_length=50, description="Restrict to beneficiaries in this status."
    )
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Case-insensitive fragment of the saved recipient's display name to match.",
    )


__all__ = ["BeneficiariesRequest", "PaymentActivityRequest", "UpcomingPaymentsRequest"]
