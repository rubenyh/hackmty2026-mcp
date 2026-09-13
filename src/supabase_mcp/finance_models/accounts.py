"""Account and statement request contracts."""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from supabase_mcp.finance_models._shared import AccountIds, Pagination, _ScopedRequest


class AccountsRequest(_ScopedRequest):
    account_ids: AccountIds = Field(
        default_factory=list, description="Restrict to these account ids; empty means all accounts."
    )
    account_type: str | None = Field(
        default=None,
        max_length=50,
        description="Restrict to one account type, such as checking, savings or credit.",
    )
    include_cards: bool = Field(
        default=True, description="Include masked card metadata for each account."
    )
    include_credit_terms: bool = Field(
        default=True, description="Include current credit-card terms such as limit, cutoff and due."
    )
    status: str | None = Field(
        default=None, max_length=50, description="Restrict to accounts in this status."
    )


class CreditCardsRequest(_ScopedRequest):
    """Filters for the user's credit-card portfolio."""

    account_ids: AccountIds = Field(
        default_factory=list,
        description="Restrict to cards on these account ids; empty means all credit accounts.",
    )
    status: Literal["active", "blocked", "inactive"] | None = Field(
        default=None, description="Restrict to cards in this status; omit for every credit card."
    )


class BankStatementsRequest(_ScopedRequest, Pagination):
    account_ids: AccountIds = Field(
        default_factory=list, description="Restrict to these account ids; empty means all accounts."
    )
    period_start: date | None = Field(
        default=None, description="Keep statements whose period starts on or after this date."
    )
    period_end: date | None = Field(
        default=None, description="Keep statements whose period ends on or before this date."
    )
    document_status: str | None = Field(
        default=None,
        max_length=50,
        description="Restrict to statements in this document status, such as available.",
    )

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise PydanticCustomError(
                "invalid_date_range", "period_end must be on or after period_start"
            )
        return self


__all__ = ["AccountsRequest", "BankStatementsRequest", "CreditCardsRequest"]
