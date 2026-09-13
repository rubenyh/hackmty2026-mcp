"""Debt request contracts."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from supabase_mcp.finance_models._shared import AccountIds, ResourceIds, _ScopedRequest


class DebtOverviewRequest(_ScopedRequest):
    debt_ids: ResourceIds = Field(default_factory=list)
    account_ids: AccountIds = Field(default_factory=list)
    status: Literal["active", "paid", "all"] = "active"
    include_credit_cards: bool = True
    include_scenarios: bool = True


class CompareDebtScenariosRequest(_ScopedRequest):
    debt_id: UUID = Field(description="Debt to compare, as returned by get_debt_overview")
    scenario_ids: ResourceIds = Field(default_factory=list)
    order_by: Literal["lowest_total_interest", "lowest_monthly_payment", "fastest_payoff"] = Field(
        default="lowest_total_interest",
        description="Ranking criterion for the saved scenarios / Criterio de orden",
    )


__all__ = ["CompareDebtScenariosRequest", "DebtOverviewRequest"]
