"""Savings request contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from supabase_mcp.finance_models._shared import AccountIds, ResourceIds, _ScopedRequest


class SavingsProgressRequest(_ScopedRequest):
    goal_ids: ResourceIds = Field(
        default_factory=list, description="Restrict to these savings goal ids; empty means all."
    )
    status: Literal["active", "completed", "all"] = Field(
        default="active", description="Keep active goals, completed ones, or all of them."
    )
    account_ids: AccountIds = Field(
        default_factory=list, description="Restrict to goals of these account ids."
    )
    include_contributions: bool = Field(
        default=False, description="Also return the recent contributions made to each goal."
    )
    contributions_limit: int = Field(
        default=20, ge=1, le=100, description="Maximum contributions to return per request."
    )


__all__ = ["SavingsProgressRequest"]
