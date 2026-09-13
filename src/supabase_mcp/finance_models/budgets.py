"""Budget request contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from supabase_mcp.finance_models._shared import AccountIds, ResourceIds, _ScopedRequest


class BudgetProgressRequest(_ScopedRequest):
    budget_ids: ResourceIds = Field(default_factory=list)
    status: Literal["active", "completed", "all"] = "active"
    category: str | None = Field(
        default=None,
        max_length=100,
        description="Restrict to one budget category such as food / Una sola categoria",
    )
    account_ids: AccountIds = Field(default_factory=list)
    include_expired: bool = False


__all__ = ["BudgetProgressRequest"]
