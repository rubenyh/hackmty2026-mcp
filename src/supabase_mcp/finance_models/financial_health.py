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
    period: Literal["current_month", "previous_month", "last_30_days", "current_year"] = (
        "current_month"
    )
    account_ids: AccountIds = Field(default_factory=list)


class FinancialAlertsRequest(_ScopedRequest, Pagination):
    status: Literal["active", "dismissed", "all"] = "active"
    kinds: list[str] = Field(default_factory=list, max_length=20)
    account_ids: AccountIds = Field(default_factory=list)
    budget_ids: ResourceIds = Field(default_factory=list)
    due_within_days: int | None = Field(
        default=None,
        ge=0,
        le=365,
        description="Keep only alerts due inside this many days / Vencen en N dias",
    )


__all__ = ["FinancialAlertsRequest", "FinancialOverviewRequest"]
