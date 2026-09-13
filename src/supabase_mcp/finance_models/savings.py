"""Savings request contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from supabase_mcp.finance_models._shared import AccountIds, ResourceIds, _ScopedRequest


class SavingsProgressRequest(_ScopedRequest):
    goal_ids: ResourceIds = Field(default_factory=list)
    status: Literal["active", "completed", "all"] = "active"
    account_ids: AccountIds = Field(default_factory=list)
    include_contributions: bool = False
    contributions_limit: int = Field(default=20, ge=1, le=100)


__all__ = ["SavingsProgressRequest"]
