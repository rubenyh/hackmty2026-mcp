"""Owned database assembly and inference orchestration for prediction tools."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError

from supabase_mcp.database import DatabaseClient
from supabase_mcp.errors import SafeMCPError
from supabase_mcp.finance_models.predictions import (
    AnomalyDetectionInferenceRequest,
    CashBalanceInferenceRequest,
    DetectTransactionAnomaliesRequest,
    ForecastCashBalanceRequest,
    ForecastRecurringChargesRequest,
    NormalizedTransaction,
    PredictSavingsGoalRequest,
    RecurringChargesInferenceRequest,
    SavingsContribution,
    SavingsGoalInferenceRequest,
    SavingsGoalInput,
    ScheduledCashFlow,
)
from supabase_mcp.inference import InferenceClient
from supabase_mcp.models import FilterCondition, FilterOperator, OrderBy, OrderDirection, UserScope
from supabase_mcp.services.finance._shared import (
    _filters_for_accounts,
    _owned_accounts,
    _select,
)

# The models contract allows 10,000 records, but the MCP read boundary intentionally
# uses the most recent 500 per history collection. No undocumented time window is imposed.
PREDICTION_HISTORY_LIMIT = 500
ModelT = TypeVar("ModelT", bound=BaseModel)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _decimal(value: object) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SafeMCPError("invalid_data", "A stored financial amount is invalid.") from exc
    if not parsed.is_finite():
        raise SafeMCPError("invalid_data", "A stored financial amount is invalid.")
    return parsed


def _amount(value: object) -> float:
    parsed = abs(_decimal(value))
    if parsed <= 0:
        raise SafeMCPError("invalid_data", "A stored financial amount is invalid.")
    return float(parsed)


def _positive_amount(value: object) -> float:
    parsed = _decimal(value)
    if parsed <= 0:
        raise SafeMCPError("invalid_data", "A stored financial amount is invalid.")
    return float(parsed)


def _model_or_data_error(model: type[ModelT], values: Mapping[str, object]) -> ModelT:
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        raise SafeMCPError("invalid_data", "Stored financial data cannot be normalized.") from exc


def _transaction(row: Mapping[str, object]) -> NormalizedTransaction:
    merchant_value = row.get("merchant")
    merchant = str(merchant_value).strip() if merchant_value is not None else None
    return _model_or_data_error(
        NormalizedTransaction,
        {
            "transaction_id": str(row["id"]),
            "amount": _amount(row["amount"]),
            "direction": row["direction"],
            "category": str(row.get("category") or "uncategorized"),
            "merchant": merchant or None,
            "occurred_at": row["occurred_at"],
        },
    )


def _contribution(row: Mapping[str, object]) -> SavingsContribution:
    return _model_or_data_error(
        SavingsContribution,
        {
            "contribution_id": str(row["id"]),
            "amount": _positive_amount(row["amount"]),
            "contributed_at": row["contributed_at"],
        },
    )


def _scheduled_flow(row: Mapping[str, object]) -> ScheduledCashFlow:
    return _model_or_data_error(
        ScheduledCashFlow,
        {
            "cash_flow_id": str(row["id"]),
            "name": str(row["name"]),
            "amount": _amount(row["amount"]),
            "direction": row["direction"],
            "scheduled_date": row["scheduled_date"],
        },
    )


async def _recent_transactions(
    database: DatabaseClient,
    scope: UserScope,
    account_ids: Sequence[UUID],
    as_of: datetime,
) -> list[NormalizedTransaction]:
    rows, _ = await _select(
        database,
        scope,
        "transactions",
        ["id", "account_id", "amount", "direction", "category", "merchant", "occurred_at"],
        filters=[
            *_filters_for_accounts("account_id", account_ids),
            FilterCondition(
                column="occurred_at", operator=FilterOperator.LTE, value=as_of.isoformat()
            ),
        ],
        order_by=[
            OrderBy(column="occurred_at", direction=OrderDirection.DESC),
            OrderBy(column="id", direction=OrderDirection.DESC),
        ],
        limit=PREDICTION_HISTORY_LIMIT,
    )
    normalized = [_transaction(row) for row in rows]
    return sorted(normalized, key=lambda item: (item.occurred_at, item.transaction_id))


class PredictionService:
    """Assemble owned records and delegate only normalized data to Models API."""

    def __init__(
        self,
        database: DatabaseClient,
        inference: InferenceClient,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._database = database
        self._inference = inference
        self._clock = clock

    def _as_of(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise SafeMCPError("invalid_data", "Prediction time must include a timezone.")
        return value.astimezone(UTC)

    async def forecast_cash_balance(self, request: ForecastCashBalanceRequest) -> dict[str, Any]:
        as_of = self._as_of()
        account = (await _owned_accounts(self._database, request.scope, [request.account_id]))[0]
        currency = str(account["currency"]).upper()
        transactions = await _recent_transactions(
            self._database, request.scope, [request.account_id], as_of
        )
        end_date = as_of.date() + timedelta(days=request.horizon_days)
        flow_rows, flow_truncated = await _select(
            self._database,
            request.scope,
            "scheduled_cash_flows",
            ["id", "account_id", "name", "direction", "amount", "currency", "scheduled_date"],
            filters=[
                FilterCondition(
                    column="account_id", operator=FilterOperator.EQ, value=str(request.account_id)
                ),
                FilterCondition(
                    column="scheduled_date",
                    operator=FilterOperator.GTE,
                    value=as_of.date().isoformat(),
                ),
                FilterCondition(
                    column="scheduled_date",
                    operator=FilterOperator.LTE,
                    value=end_date.isoformat(),
                ),
                FilterCondition(
                    column="status",
                    operator=FilterOperator.IN,
                    value=["expected", "confirmed"],
                ),
                FilterCondition(column="currency", operator=FilterOperator.EQ, value=currency),
            ],
            order_by=[OrderBy(column="scheduled_date"), OrderBy(column="id")],
            limit=PREDICTION_HISTORY_LIMIT,
        )
        if flow_truncated:
            raise SafeMCPError("invalid_data", "Scheduled cash-flow history exceeds the limit.")
        flows = sorted(
            [_scheduled_flow(row) for row in flow_rows],
            key=lambda item: (item.scheduled_date, item.cash_flow_id),
        )
        payload = _model_or_data_error(
            CashBalanceInferenceRequest,
            {
                "request_id": uuid4(),
                "as_of": as_of,
                "currency": currency,
                "current_balance": float(_decimal(account["available_balance"])),
                "horizon_days": request.horizon_days,
                "transactions": transactions,
                "scheduled_cash_flows": flows,
            },
        )
        response = await self._inference.forecast_cash_balance(payload)
        return response.model_dump(mode="python")

    async def predict_savings_goal(self, request: PredictSavingsGoalRequest) -> dict[str, Any]:
        as_of = self._as_of()
        goal_rows, _ = await _select(
            self._database,
            request.scope,
            "savings_goals",
            ["id", "account_id", "currency", "target_amount", "target_date"],
            filters=[
                FilterCondition(column="id", operator=FilterOperator.EQ, value=str(request.goal_id))
            ],
            limit=1,
        )
        if not goal_rows:
            raise SafeMCPError("resource_not_found", "The requested savings goal was not found.")
        goal_row = goal_rows[0]

        contribution_rows, contribution_truncated = await _select(
            self._database,
            request.scope,
            "savings_contributions",
            ["id", "goal_id", "amount", "contributed_at"],
            filters=[
                FilterCondition(
                    column="goal_id", operator=FilterOperator.EQ, value=str(request.goal_id)
                ),
                FilterCondition(
                    column="contributed_at", operator=FilterOperator.LTE, value=as_of.isoformat()
                ),
            ],
            order_by=[
                OrderBy(column="contributed_at", direction=OrderDirection.DESC),
                OrderBy(column="id", direction=OrderDirection.DESC),
            ],
            limit=PREDICTION_HISTORY_LIMIT,
        )
        if contribution_truncated:
            raise SafeMCPError("invalid_data", "Savings contribution history exceeds the limit.")
        contributions = sorted(
            [_contribution(row) for row in contribution_rows],
            key=lambda item: (item.contributed_at, item.contribution_id or ""),
        )

        account_id = goal_row.get("account_id")
        goal_currency = str(goal_row["currency"]).upper()
        if account_id is not None:
            account_ids = [UUID(str(account_id))]
            owned_account = (await _owned_accounts(self._database, request.scope, account_ids))[0]
            if str(owned_account["currency"]).upper() != goal_currency:
                raise SafeMCPError("invalid_data", "Savings goal currency is inconsistent.")
        else:
            accounts = await _owned_accounts(self._database, request.scope)
            account_ids = [
                UUID(str(account["id"]))
                for account in accounts
                if str(account["currency"]).upper() == goal_currency
            ]
        cash_history = (
            await _recent_transactions(self._database, request.scope, account_ids, as_of)
            if account_ids
            else []
        )
        current_saved = sum((Decimal(str(item.amount)) for item in contributions), Decimal("0"))
        goal = _model_or_data_error(
            SavingsGoalInput,
            {
                "goal_id": str(goal_row["id"]),
                "target_amount": _positive_amount(goal_row["target_amount"]),
                "target_date": goal_row["target_date"],
                "current_saved_amount": float(current_saved),
            },
        )
        payload = _model_or_data_error(
            SavingsGoalInferenceRequest,
            {
                "request_id": uuid4(),
                "as_of": as_of,
                "currency": goal_currency,
                "goal": goal,
                "contributions": contributions,
                "cash_flow_history": cash_history,
            },
        )
        response = await self._inference.predict_savings_goal(payload)
        return response.model_dump(mode="python")

    async def forecast_recurring_charges(
        self, request: ForecastRecurringChargesRequest
    ) -> dict[str, Any]:
        as_of = self._as_of()
        account = (await _owned_accounts(self._database, request.scope, [request.account_id]))[0]
        transactions = await _recent_transactions(
            self._database, request.scope, [request.account_id], as_of
        )
        payload = _model_or_data_error(
            RecurringChargesInferenceRequest,
            {
                "request_id": uuid4(),
                "as_of": as_of,
                "currency": str(account["currency"]).upper(),
                "forecast_days": request.forecast_days,
                "transactions": transactions,
            },
        )
        response = await self._inference.forecast_recurring_charges(payload)
        return response.model_dump(mode="python")

    async def detect_transaction_anomalies(
        self, request: DetectTransactionAnomaliesRequest
    ) -> dict[str, Any]:
        as_of = self._as_of()
        account = (await _owned_accounts(self._database, request.scope, [request.account_id]))[0]
        transactions = await _recent_transactions(
            self._database, request.scope, [request.account_id], as_of
        )
        candidate_start = as_of - timedelta(days=request.candidate_days)
        historical = [item for item in transactions if item.occurred_at < candidate_start]
        candidates = [item for item in transactions if item.occurred_at >= candidate_start]
        payload = _model_or_data_error(
            AnomalyDetectionInferenceRequest,
            {
                "request_id": uuid4(),
                "as_of": as_of,
                "currency": str(account["currency"]).upper(),
                "historical_transactions": historical,
                "candidate_transactions": candidates,
            },
        )
        response = await self._inference.detect_transaction_anomalies(payload)
        return response.model_dump(mode="python")


__all__ = ["PREDICTION_HISTORY_LIMIT", "PredictionService"]
