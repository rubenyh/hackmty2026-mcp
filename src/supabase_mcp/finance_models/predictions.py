"""Semantic MCP inputs and strict models-service wire contracts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator

from supabase_mcp.models import StrictModel, UserScope

Confidence = Annotated[float, Field(ge=0, le=1)]


class ForecastCashBalanceRequest(StrictModel):
    """Select one owned account and an allowed liquidity forecast horizon."""

    scope: UserScope
    account_id: UUID = Field(
        description="Account whose future balance is projected; must belong to the user."
    )
    horizon_days: Literal[7, 15, 30] = Field(
        default=30,
        description="How many days ahead to project the balance: 7, 15 or 30.",
    )


class PredictSavingsGoalRequest(StrictModel):
    """Select one owned savings goal for completion probability and date prediction."""

    scope: UserScope
    goal_id: UUID = Field(
        description="Savings goal whose completion is predicted; must belong to the user."
    )


class ForecastRecurringChargesRequest(StrictModel):
    """Select one owned account and a future recurring-charge forecast period."""

    scope: UserScope
    account_id: UUID = Field(
        description="Account whose repeating charges are forecast; must belong to the user."
    )
    forecast_days: int = Field(
        default=30,
        ge=7,
        le=365,
        description="How many days ahead to forecast expected charges, from 7 to 365.",
    )


class DetectTransactionAnomaliesRequest(StrictModel):
    """Select one owned account and the recent candidate period to evaluate."""

    scope: UserScope
    account_id: UUID = Field(
        description="Account whose transactions are scored; must belong to the user."
    )
    candidate_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description=(
            "How many of the most recent days are scored for anomalies; earlier "
            "transactions form the baseline."
        ),
    )


class NormalizedTransaction(StrictModel):
    transaction_id: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0, allow_inf_nan=False)
    direction: Literal["debit", "credit"]
    category: str = Field(min_length=1, max_length=100)
    merchant: str | None = Field(default=None, min_length=1, max_length=200)
    occurred_at: AwareDatetime

    @field_validator("occurred_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class ScheduledCashFlow(StrictModel):
    cash_flow_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=160)
    amount: float = Field(gt=0, allow_inf_nan=False)
    direction: Literal["income", "expense"]
    scheduled_date: date


class SavingsContribution(StrictModel):
    contribution_id: str | None = Field(default=None, min_length=1, max_length=200)
    amount: float = Field(gt=0, allow_inf_nan=False)
    contributed_at: AwareDatetime

    @field_validator("contributed_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class SavingsGoalInput(StrictModel):
    goal_id: str = Field(min_length=1, max_length=200)
    target_amount: float = Field(gt=0, allow_inf_nan=False)
    target_date: date
    current_saved_amount: float = Field(ge=0, allow_inf_nan=False)


class InferenceRequest(StrictModel):
    request_id: UUID
    as_of: AwareDatetime
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")

    @field_validator("as_of")
    @classmethod
    def normalize_as_of(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class CashBalanceInferenceRequest(InferenceRequest):
    current_balance: float = Field(allow_inf_nan=False)
    horizon_days: Literal[7, 15, 30]
    transactions: list[NormalizedTransaction] = Field(max_length=10_000)
    scheduled_cash_flows: list[ScheduledCashFlow] = Field(max_length=10_000)

    @model_validator(mode="after")
    def validate_records(self) -> Self:
        _validate_record_count(self.transactions, self.scheduled_cash_flows)
        _validate_ordered_history(self.transactions, self.as_of)
        dates = [item.scheduled_date for item in self.scheduled_cash_flows]
        if dates != sorted(dates) or any(value < self.as_of.date() for value in dates):
            raise ValueError("scheduled cash flows must be chronological and not before as_of")
        return self


class SavingsGoalInferenceRequest(InferenceRequest):
    goal: SavingsGoalInput
    contributions: list[SavingsContribution] = Field(max_length=10_000)
    cash_flow_history: list[NormalizedTransaction] = Field(max_length=10_000)

    @model_validator(mode="after")
    def validate_records(self) -> Self:
        _validate_record_count(self.contributions, self.cash_flow_history)
        contribution_times = [item.contributed_at for item in self.contributions]
        if contribution_times != sorted(contribution_times) or any(
            value > self.as_of for value in contribution_times
        ):
            raise ValueError("contributions must be chronological history")
        _validate_ordered_history(self.cash_flow_history, self.as_of)
        if self.goal.target_date < self.as_of.date():
            raise ValueError("goal target_date cannot be before as_of")
        return self


class RecurringChargesInferenceRequest(InferenceRequest):
    forecast_days: int = Field(ge=7, le=365)
    transactions: list[NormalizedTransaction] = Field(max_length=10_000)

    @model_validator(mode="after")
    def validate_records(self) -> Self:
        _validate_record_count(self.transactions)
        _validate_ordered_history(self.transactions, self.as_of)
        return self


class AnomalyDetectionInferenceRequest(InferenceRequest):
    historical_transactions: list[NormalizedTransaction] = Field(max_length=10_000)
    candidate_transactions: list[NormalizedTransaction] = Field(max_length=10_000)

    @model_validator(mode="after")
    def validate_records(self) -> Self:
        _validate_record_count(self.historical_transactions, self.candidate_transactions)
        _validate_ordered_history(self.historical_transactions, self.as_of)
        _validate_ordered_history(self.candidate_transactions, self.as_of)
        if (
            self.historical_transactions
            and self.candidate_transactions
            and self.candidate_transactions[0].occurred_at
            < self.historical_transactions[-1].occurred_at
        ):
            raise ValueError("candidate transactions cannot precede historical transactions")
        return self


def _validate_record_count(*groups: Sequence[object]) -> None:
    if sum(len(group) for group in groups) > 10_000:
        raise ValueError("inference requests accept at most 10000 records")


def _validate_ordered_history(records: list[NormalizedTransaction], as_of: datetime) -> None:
    times = [item.occurred_at for item in records]
    if times != sorted(times) or any(value > as_of for value in times):
        raise ValueError("transactions must be chronological history")


class PredictionDriver(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    impact: float | None = Field(default=None, allow_inf_nan=False)
    description: str = Field(min_length=1, max_length=500)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class PredictionResponse(StrictModel):
    request_id: UUID
    model_name: Literal[
        "forecast_cash_balance",
        "predict_savings_goal",
        "forecast_recurring_charges",
        "detect_transaction_anomalies",
    ]
    model_version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    trained_until: AwareDatetime
    generated_at: AwareDatetime
    confidence: Confidence
    drivers: list[PredictionDriver] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("trained_until", "generated_at")
    @classmethod
    def normalize_response_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class CashBalanceSummary(StrictModel):
    currency: str = Field(min_length=3, max_length=3)
    starting_balance: float = Field(allow_inf_nan=False)
    expected_ending_balance: float = Field(allow_inf_nan=False)
    expected_minimum_balance: float = Field(allow_inf_nan=False)
    scheduled_income: float = Field(ge=0, allow_inf_nan=False)
    scheduled_expenses: float = Field(ge=0, allow_inf_nan=False)


class CashBalancePoint(StrictModel):
    date: date
    expected: float = Field(allow_inf_nan=False)
    lower_bound: float = Field(allow_inf_nan=False)
    upper_bound: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if not self.lower_bound <= self.expected <= self.upper_bound:
            raise ValueError("cash balance bounds are invalid")
        return self


class CashBalancePredictionResponse(PredictionResponse):
    model_name: Literal["forecast_cash_balance"]
    summary: CashBalanceSummary
    series: list[CashBalancePoint]
    items: list[CashBalancePoint] = Field(default_factory=list)


class SavingsGoalSummary(StrictModel):
    currency: str = Field(min_length=3, max_length=3)
    target_amount: float = Field(gt=0, allow_inf_nan=False)
    current_amount: float = Field(ge=0, allow_inf_nan=False)
    probability_of_success: Confidence
    conservative_completion_date: date | None
    expected_completion_date: date | None
    optimistic_completion_date: date | None
    recommended_monthly_contribution: float = Field(ge=0, allow_inf_nan=False)


class SavingsGoalPoint(StrictModel):
    date: date
    conservative: float = Field(allow_inf_nan=False)
    expected: float = Field(allow_inf_nan=False)
    optimistic: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_quantiles(self) -> Self:
        if not self.conservative <= self.expected <= self.optimistic:
            raise ValueError("savings goal quantiles are invalid")
        return self


class SavingsGoalPredictionResponse(PredictionResponse):
    model_name: Literal["predict_savings_goal"]
    summary: SavingsGoalSummary
    series: list[SavingsGoalPoint]
    items: list[SavingsGoalPoint] = Field(default_factory=list)


class RecurringChargesSummary(StrictModel):
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    patterns_detected: int = Field(ge=0)
    expected_total: float = Field(ge=0, allow_inf_nan=False)


class RecurringChargePoint(StrictModel):
    normalized_merchant: str = Field(min_length=1, max_length=200)
    next_expected_date: date
    expected_amount: float = Field(gt=0, allow_inf_nan=False)
    interval_days: float = Field(gt=0, allow_inf_nan=False)
    confidence: Confidence
    observations: int = Field(ge=2)


class RecurringChargesPredictionResponse(PredictionResponse):
    model_name: Literal["forecast_recurring_charges"]
    summary: RecurringChargesSummary
    series: list[RecurringChargePoint] = Field(default_factory=list)
    items: list[RecurringChargePoint]


class AnomalySummary(StrictModel):
    transactions_analyzed: int = Field(ge=0)
    anomalies_detected: int = Field(ge=0)


class AnomalyPoint(StrictModel):
    transaction_id: str = Field(min_length=1, max_length=200)
    occurred_at: AwareDatetime
    signed_amount: float = Field(allow_inf_nan=False)
    anomaly_score: float = Field(allow_inf_nan=False)
    severity: Literal["low", "medium", "high"]
    reasons: list[str] = Field(min_length=1)


class AnomalyDetectionPredictionResponse(PredictionResponse):
    model_name: Literal["detect_transaction_anomalies"]
    summary: AnomalySummary
    series: list[AnomalyPoint] = Field(default_factory=list)
    items: list[AnomalyPoint]


__all__ = [
    "AnomalyDetectionInferenceRequest",
    "AnomalyDetectionPredictionResponse",
    "CashBalanceInferenceRequest",
    "CashBalancePredictionResponse",
    "DetectTransactionAnomaliesRequest",
    "ForecastCashBalanceRequest",
    "ForecastRecurringChargesRequest",
    "NormalizedTransaction",
    "PredictSavingsGoalRequest",
    "RecurringChargesInferenceRequest",
    "RecurringChargesPredictionResponse",
    "SavingsContribution",
    "SavingsGoalInferenceRequest",
    "SavingsGoalInput",
    "SavingsGoalPredictionResponse",
    "ScheduledCashFlow",
]
