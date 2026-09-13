"""Cash-flow request contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from supabase_mcp.finance_models._shared import AccountIds, _PeriodRequest


class CashFlowRequest(_PeriodRequest):
    period: Literal[
        "last_3_months", "last_6_months", "last_12_months", "current_year", "custom"
    ] = "last_6_months"  # type: ignore[assignment]
    account_ids: AccountIds = Field(
        default_factory=list, description="Restrict to these account ids; empty means all accounts."
    )


__all__ = ["CashFlowRequest"]
