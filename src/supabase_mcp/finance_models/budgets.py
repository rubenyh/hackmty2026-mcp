"""Budget request contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from supabase_mcp.finance_models._shared import AccountIds, ResourceIds, _ScopedRequest


class BudgetProgressRequest(_ScopedRequest):
    budget_ids: ResourceIds = Field(
        default_factory=list, description="Restrict to these budget ids; empty means every budget."
    )
    status: Literal["active", "completed", "all"] = Field(
        default="active", description="Keep active budgets, completed ones, or all of them."
    )
    category: str | None = Field(
        default=None,
        max_length=100,
        description="Restrict to a single budget category, such as groceries or transport.",
    )
    account_ids: AccountIds = Field(
        default_factory=list, description="Restrict to budgets of these account ids."
    )
    include_expired: bool = Field(
        default=False, description="Also include budgets whose period has already ended."
    )


__all__ = ["BudgetProgressRequest"]
