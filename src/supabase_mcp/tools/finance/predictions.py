"""Thin MCP handlers for owned financial predictions."""

from __future__ import annotations

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.predictions import (
    DetectTransactionAnomaliesRequest,
    ForecastCashBalanceRequest,
    ForecastRecurringChargesRequest,
    PredictSavingsGoalRequest,
)
from supabase_mcp.services.finance.predictions import PredictionService
from supabase_mcp.tools.finance._shared import _run_with_dependency


def _prediction_service(ctx: Context) -> PredictionService:
    service = ctx.lifespan_context.get("predictions")
    if not isinstance(service, PredictionService):
        raise RuntimeError("prediction service lifespan context is unavailable")
    return service


async def forecast_cash_balance(request: ForecastCashBalanceRequest, ctx: Context) -> ToolResult:
    """Future cash balance and liquidity forecast / Pronóstico de saldo y liquidez futura.

    Predicts one owned account's 7, 15, or 30-day balance path using transaction
    history and scheduled cash flows. Not a historical cash-flow report. Claves:
    future balance, cash forecast, liquidity, saldo futuro, pronostico, liquidez.
    """
    return await _run_with_dependency(
        "forecast_cash_balance",
        request,
        ctx,
        _prediction_service(ctx),
        PredictionService.forecast_cash_balance,
    )


async def predict_savings_goal(request: PredictSavingsGoalRequest, ctx: Context) -> ToolResult:
    """Savings goal completion probability and date / Probabilidad y fecha de una meta de ahorro.

    Predicts whether and when one owned goal will be completed from contributions
    and cash-flow history. Not the stored progress snapshot. Claves: goal forecast,
    complete savings goal on time, completion probability, completion date,
    completare meta de ahorro, cuando completare, probabilidad, fecha estimada.
    """
    return await _run_with_dependency(
        "predict_savings_goal",
        request,
        ctx,
        _prediction_service(ctx),
        PredictionService.predict_savings_goal,
    )


async def forecast_recurring_charges(
    request: ForecastRecurringChargesRequest, ctx: Context
) -> ToolResult:
    """Expected recurring or subscription-like charges / Cargos recurrentes esperados.

    Finds repeating merchant patterns in one owned account and forecasts future
    charge dates and amounts. Not a list of known scheduled payments. Claves:
    recurring charges, subscriptions, expected charge, cargos recurrentes, suscripciones.
    """
    return await _run_with_dependency(
        "forecast_recurring_charges",
        request,
        ctx,
        _prediction_service(ctx),
        PredictionService.forecast_recurring_charges,
    )


async def detect_transaction_anomalies(
    request: DetectTransactionAnomaliesRequest, ctx: Context
) -> ToolResult:
    """Unusual or anomalous transaction detection / Detección de movimientos inusuales.

    Scores recent transactions in one owned account against its earlier history
    and explains anomalies. Not a dispute lookup or generic transaction list.
    Claves: anomaly, anomalous transactions, unusual transaction, suspicious charge,
    anomalía, anomalos, movimientos anomalos, movimiento inusual.
    """
    return await _run_with_dependency(
        "detect_transaction_anomalies",
        request,
        ctx,
        _prediction_service(ctx),
        PredictionService.detect_transaction_anomalies,
    )


__all__ = [
    "detect_transaction_anomalies",
    "forecast_cash_balance",
    "forecast_recurring_charges",
    "predict_savings_goal",
]
