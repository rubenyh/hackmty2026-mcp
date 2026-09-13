"""Thin MCP handlers for owned financial predictions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from fastmcp import Context
from fastmcp.tools import ToolResult
from pydantic import BaseModel

from supabase_mcp.errors import SafeMCPError
from supabase_mcp.finance_models.predictions import (
    DetectTransactionAnomaliesRequest,
    ForecastCashBalanceRequest,
    ForecastRecurringChargesRequest,
    PredictSavingsGoalRequest,
)
from supabase_mcp.services.finance.predictions import PredictionService
from supabase_mcp.tools.finance._shared import _run_with_dependency

RequestT = TypeVar("RequestT", bound=BaseModel)


def _prediction_service(ctx: Context) -> PredictionService:
    """Return the lifespan-managed prediction service or fail as a safe error."""
    service = ctx.lifespan_context.get("predictions")
    if not isinstance(service, PredictionService):
        raise SafeMCPError(
            "INFERENCE_NOT_CONFIGURED", "The prediction service is not available."
        )
    return service


async def _run_prediction(
    tool: str,
    request: RequestT,
    ctx: Context,
    method: Callable[[PredictionService, RequestT], Awaitable[dict[str, Any]]],
) -> ToolResult:
    """Resolve the prediction service inside the shared structured-error boundary.

    Resolving it eagerly would let a missing lifespan entry escape as an opaque
    tool failure instead of the classified, correlated error every other
    financial tool returns.
    """

    @wraps(method)
    async def handler(context: Context, payload: RequestT) -> dict[str, Any]:
        return await method(_prediction_service(context), payload)

    return await _run_with_dependency(tool, request, ctx, ctx, handler)


async def forecast_cash_balance(request: ForecastCashBalanceRequest, ctx: Context) -> ToolResult:
    """Project one account's cash balance forward over the next few weeks.

    Runs the balance-forecast model over the account's transaction history and
    its confirmed or expected scheduled cash flows. Returns a day-by-day
    expected balance path with lower and upper bounds over a 7, 15 or 30 day
    horizon, a summary with the expected ending and minimum balance against
    scheduled income and expenses, the drivers behind the projection and its
    confidence. Use it when the user asks whether money will last, whether a
    balance will run low, or what the balance will be on a future date.
    get_cash_flow reports the income and expenses already recorded; this tool
    projects a balance that has not happened yet.
    """
    return await _run_prediction(
        "forecast_cash_balance", request, ctx, PredictionService.forecast_cash_balance
    )


async def predict_savings_goal(request: PredictSavingsGoalRequest, ctx: Context) -> ToolResult:
    """Estimate whether and when one savings goal will be reached.

    Runs the savings-goal model over the goal's recorded contributions and the
    cash-flow history of the accounts in its currency. Returns the probability
    of reaching the target, conservative, expected and optimistic completion
    dates, a recommended monthly contribution, a projected accumulation series
    and the drivers behind the estimate. Use it when the user asks whether a
    goal will be met on time, when it will be finished, or how much to put
    aside each month. get_savings_progress reports how much is saved today;
    this tool projects the outcome.
    """
    return await _run_prediction(
        "predict_savings_goal", request, ctx, PredictionService.predict_savings_goal
    )


async def forecast_recurring_charges(
    request: ForecastRecurringChargesRequest, ctx: Context
) -> ToolResult:
    """Predict the subscription-like charges an account will receive next.

    Runs the recurring-charge model over the account's transaction history to
    find repeating merchant patterns. Returns one entry per detected pattern
    with the normalized merchant, the next expected charge date and amount, the
    observed interval and how many observations support it, plus the expected
    total over a 7 to 365 day window. Use it when the user asks what is going
    to be charged, which subscriptions are coming, or what repeats every month.
    get_upcoming_payments lists payments already scheduled in the ledger; this
    tool infers charges nobody has scheduled yet.
    """
    return await _run_prediction(
        "forecast_recurring_charges", request, ctx, PredictionService.forecast_recurring_charges
    )


async def detect_transaction_anomalies(
    request: DetectTransactionAnomaliesRequest, ctx: Context
) -> ToolResult:
    """Score an account's most recent transactions for unusual activity.

    Runs the anomaly-detection model over the account's recent transactions,
    using its earlier transactions as the baseline. Returns each flagged
    transaction with an anomaly score, a low, medium or high severity and the
    reasons it stands out, plus how many transactions were analyzed. Use it
    when the user asks about strange, unexpected or suspicious activity, or
    wants a review of what looks out of place. get_transaction_disputes lists
    claims the user already opened and get_transactions lists movements without
    judging them; this tool decides which ones are abnormal.
    """
    return await _run_prediction(
        "detect_transaction_anomalies", request, ctx, PredictionService.detect_transaction_anomalies
    )


__all__ = [
    "detect_transaction_anomalies",
    "forecast_cash_balance",
    "forecast_recurring_charges",
    "predict_savings_goal",
]
