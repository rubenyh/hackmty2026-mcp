"""Financial overview and alert request contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from supabase_mcp.finance_models._shared import (
    AccountIds,
    Pagination,
    ResourceIds,
    _ScopedRequest,
)


class FinancialOverviewRequest(_ScopedRequest):
    period: Literal["current_month", "previous_month", "last_30_days", "current_year"] = Field(
        default="current_month",
        description="Named date range the income, expense and net totals cover.",
    )
    account_ids: AccountIds = Field(
        default_factory=list, description="Restrict to these account ids; empty means all accounts."
    )


class FinancialAlertsRequest(_ScopedRequest, Pagination):
    status: Literal["active", "dismissed", "all"] = Field(
        default="active", description="Keep active alerts, dismissed ones, or all of them."
    )
    kinds: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Restrict to these alert kinds, such as overdraft risk or budget overrun.",
    )
    account_ids: AccountIds = Field(
        default_factory=list, description="Restrict to alerts of these account ids."
    )
    budget_ids: ResourceIds = Field(
        default_factory=list, description="Restrict to alerts raised for these budget ids."
    )
    due_within_days: int | None = Field(
        default=None,
        ge=0,
        le=365,
        description="Keep only alerts whose due date falls inside this many days from today.",
    )


__all__ = ["FinancialAlertsRequest", "FinancialOverviewRequest"]
