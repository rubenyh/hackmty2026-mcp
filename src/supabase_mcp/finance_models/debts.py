"""Debt request contracts."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from supabase_mcp.finance_models._shared import AccountIds, ResourceIds, _ScopedRequest


class DebtOverviewRequest(_ScopedRequest):
    debt_ids: ResourceIds = Field(
        default_factory=list, description="Restrict to these debt ids; empty means every debt."
    )
    account_ids: AccountIds = Field(
        default_factory=list, description="Restrict to these account ids; empty means all accounts."
    )
    status: Literal["active", "paid", "all"] = Field(
        default="active", description="Keep debts still owed, debts already paid, or all of them."
    )
    include_credit_cards: bool = Field(
        default=True, description="Include credit-card terms, balances and utilization."
    )
    include_scenarios: bool = Field(
        default=True,
        description="Include the payoff projections stored for each debt; "
        "compare_debt_scenarios ranks them.",
    )


class CompareDebtScenariosRequest(_ScopedRequest):
    debt_id: UUID = Field(
        description="Id of the single debt whose scenarios to compare, from get_debt_overview."
    )
    scenario_ids: ResourceIds = Field(
        default_factory=list,
        description="Restrict to these scenario ids; empty compares every scenario of the debt.",
    )
    order_by: Literal["lowest_total_interest", "lowest_monthly_payment", "fastest_payoff"] = Field(
        default="lowest_total_interest",
        description="Ranking criterion: cheapest in interest, lightest monthly, or fastest payoff.",
    )


__all__ = ["CompareDebtScenariosRequest", "DebtOverviewRequest"]
