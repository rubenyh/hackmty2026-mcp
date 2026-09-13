"""Account and statement request contracts."""

from __future__ import annotations

from datetime import date
from typing import Self

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from supabase_mcp.finance_models._shared import AccountIds, Pagination, _ScopedRequest


class AccountsRequest(_ScopedRequest):
    account_ids: AccountIds = Field(default_factory=list)
    account_type: str | None = Field(default=None, max_length=50)
    include_cards: bool = True
    include_credit_terms: bool = True
    status: str | None = Field(default=None, max_length=50)


class BankStatementsRequest(_ScopedRequest, Pagination):
    account_ids: AccountIds = Field(default_factory=list)
    period_start: date | None = None
    period_end: date | None = None
    document_status: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise PydanticCustomError(
                "invalid_date_range", "period_end must be on or after period_start"
            )
        return self


__all__ = ["AccountsRequest", "BankStatementsRequest"]
