"""Offline coverage for prediction assembly, HTTP contracts, and failures."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest

from supabase_mcp.config import Settings
from supabase_mcp.database import DatabaseClient
from supabase_mcp.errors import SafeMCPError
from supabase_mcp.finance_models.predictions import (
    CashBalanceInferenceRequest,
    DetectTransactionAnomaliesRequest,
    ForecastCashBalanceRequest,
    ForecastRecurringChargesRequest,
    PredictSavingsGoalRequest,
)
from supabase_mcp.inference import InferenceClient
from supabase_mcp.models import SelectRequest
from supabase_mcp.services.finance.predictions import PredictionService
from supabase_mcp.tools.finance.predictions import forecast_cash_balance

USER_ID = "11111111-1111-1111-1111-111111111111"
ACCOUNT_ID = "22222222-2222-2222-2222-222222222222"
OTHER_ACCOUNT_ID = "33333333-3333-3333-3333-333333333333"
GOAL_ID = "44444444-4444-4444-4444-444444444444"
AS_OF = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
FAKE_KEY = "fake-inference-key-never-log"


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "SUPABASE_DATABASE_URL": "postgresql://reader:placeholder@localhost/postgres",
            "MCP_ALLOWED_TABLES": "",
            "MCP_MAX_LIMIT": 500,
            "INFERENCE_API_URL": "https://models.test",
            "INFERENCE_API_KEY": FAKE_KEY,
        }
    )


class PredictionDatabase(DatabaseClient):
    def __init__(self, *, owns_account: bool = True) -> None:
        super().__init__(_settings())
        self.owns_account = owns_account
        self.requests: list[SelectRequest] = []

    async def select_domain_rows(
        self, request: SelectRequest
    ) -> tuple[list[dict[str, Any]], int, bool]:
        self.requests.append(request)
        rows: list[dict[str, Any]]
        if request.table == "accounts":
            rows = (
                [
                    {
                        "id": ACCOUNT_ID,
                        "account_type": "checking",
                        "currency": "MXN",
                        "available_balance": "1250.50",
                    }
                ]
                if self.owns_account
                else []
            )
        elif request.table == "transactions":
            rows = [
                {
                    "id": "txn-new",
                    "account_id": ACCOUNT_ID,
                    "amount": "50.25",
                    "direction": "debit",
                    "category": "food",
                    "merchant": "Cafe",
                    "occurred_at": "2026-09-12T10:00:00-06:00",
                },
                {
                    "id": "txn-old",
                    "account_id": ACCOUNT_ID,
                    "amount": "-1000",
                    "direction": "credit",
                    "category": "salary",
                    "merchant": "Payroll",
                    "occurred_at": "2026-08-01T10:00:00-06:00",
                },
                {
                    "id": "txn-mid",
                    "account_id": ACCOUNT_ID,
                    "amount": "-75.10",
                    "direction": "debit",
                    "category": "transport",
                    "merchant": None,
                    "occurred_at": "2026-09-10T09:00:00-06:00",
                },
            ]
        elif request.table == "scheduled_cash_flows":
            rows = [
                {
                    "id": "flow-expense",
                    "account_id": ACCOUNT_ID,
                    "name": "Rent",
                    "direction": "expense",
                    "amount": "-300",
                    "currency": "MXN",
                    "scheduled_date": "2026-09-20",
                },
                {
                    "id": "flow-income",
                    "account_id": ACCOUNT_ID,
                    "name": "Payroll",
                    "direction": "income",
                    "amount": "900",
                    "currency": "MXN",
                    "scheduled_date": "2026-09-14",
                },
            ]
        elif request.table == "savings_goals":
            rows = [
                {
                    "id": GOAL_ID,
                    "account_id": ACCOUNT_ID,
                    "currency": "MXN",
                    "target_amount": "5000",
                    "target_date": "2027-03-01",
                }
            ]
        elif request.table == "savings_contributions":
            rows = [
                {
                    "id": "contribution-new",
                    "goal_id": GOAL_ID,
                    "amount": "250",
                    "contributed_at": "2026-09-01T12:00:00Z",
                },
                {
                    "id": "contribution-old",
                    "goal_id": GOAL_ID,
                    "amount": "100",
                    "contributed_at": "2026-08-01T12:00:00Z",
                },
            ]
        else:
            rows = []
        return rows, request.limit or self.settings.default_limit, False


def _response(path: str, body: dict[str, Any]) -> dict[str, Any]:
    common = {
        "request_id": body["request_id"],
        "model_version": "0.1.0",
        "trained_until": "2026-08-31T23:59:59Z",
        "generated_at": "2026-09-13T12:00:01Z",
        "confidence": 0.8,
        "drivers": [],
        "limitations": [],
    }
    if path.endswith("/cash-balance"):
        return common | {
            "model_name": "forecast_cash_balance",
            "summary": {
                "currency": "MXN",
                "starting_balance": 1250.5,
                "expected_ending_balance": 1800,
                "expected_minimum_balance": 1200,
                "scheduled_income": 900,
                "scheduled_expenses": 300,
            },
            "series": [],
            "items": [],
        }
    if path.endswith("/savings-goal"):
        return common | {
            "model_name": "predict_savings_goal",
            "summary": {
                "currency": "MXN",
                "target_amount": 5000,
                "current_amount": 350,
                "probability_of_success": 0.7,
                "conservative_completion_date": "2027-04-01",
                "expected_completion_date": "2027-03-01",
                "optimistic_completion_date": "2027-02-01",
                "recommended_monthly_contribution": 800,
            },
            "series": [],
            "items": [],
        }
    if path.endswith("/recurring-charges"):
        return common | {
            "model_name": "forecast_recurring_charges",
            "summary": {"currency": "MXN", "patterns_detected": 0, "expected_total": 0},
            "series": [],
            "items": [],
        }
    return common | {
        "model_name": "detect_transaction_anomalies",
        "summary": {"transactions_analyzed": 2, "anomalies_detected": 0},
        "series": [],
        "items": [],
    }


async def _service_with_capture() -> tuple[
    PredictionService, list[dict[str, Any]], httpx.AsyncClient
]:
    calls: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(
            {
                "path": request.url.path,
                "authorization": request.headers.get("Authorization"),
                "body": body,
            }
        )
        return httpx.Response(200, json=_response(request.url.path, body))

    http_client = httpx.AsyncClient(
        base_url="https://models.test", transport=httpx.MockTransport(handler)
    )
    inference = InferenceClient(_settings(), client=http_client)
    service = PredictionService(PredictionDatabase(), inference, clock=lambda: AS_OF)
    return service, calls, http_client


@pytest.mark.asyncio
async def test_each_prediction_selects_its_endpoint_and_uses_service_auth() -> None:
    service, calls, http_client = await _service_with_capture()
    try:
        await service.forecast_cash_balance(
            ForecastCashBalanceRequest(scope={"user_id": USER_ID}, account_id=ACCOUNT_ID)
        )
        await service.predict_savings_goal(
            PredictSavingsGoalRequest(scope={"user_id": USER_ID}, goal_id=GOAL_ID)
        )
        await service.forecast_recurring_charges(
            ForecastRecurringChargesRequest(scope={"user_id": USER_ID}, account_id=ACCOUNT_ID)
        )
        await service.detect_transaction_anomalies(
            DetectTransactionAnomaliesRequest(scope={"user_id": USER_ID}, account_id=ACCOUNT_ID)
        )
    finally:
        await http_client.aclose()

    assert [call["path"] for call in calls] == [
        "/v1/predictions/cash-balance",
        "/v1/predictions/savings-goal",
        "/v1/predictions/recurring-charges",
        "/v1/predictions/anomalies",
    ]
    assert {call["authorization"] for call in calls} == {f"Bearer {FAKE_KEY}"}


@pytest.mark.asyncio
async def test_db_rows_are_normalized_ordered_scoped_and_identity_free() -> None:
    calls: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json=_response(request.url.path, body))

    database = PredictionDatabase()
    http_client = httpx.AsyncClient(
        base_url="https://models.test", transport=httpx.MockTransport(handler)
    )
    service = PredictionService(
        database, InferenceClient(_settings(), client=http_client), clock=lambda: AS_OF
    )
    try:
        await service.forecast_cash_balance(
            ForecastCashBalanceRequest(scope={"user_id": USER_ID}, account_id=ACCOUNT_ID)
        )
        await service.predict_savings_goal(
            PredictSavingsGoalRequest(scope={"user_id": USER_ID}, goal_id=GOAL_ID)
        )
        await service.detect_transaction_anomalies(
            DetectTransactionAnomaliesRequest(
                scope={"user_id": USER_ID}, account_id=ACCOUNT_ID, candidate_days=7
            )
        )
    finally:
        await http_client.aclose()

    cash, savings, anomalies = calls
    assert [item["transaction_id"] for item in cash["transactions"]] == [
        "txn-old",
        "txn-mid",
        "txn-new",
    ]
    assert [(item["direction"], item["amount"]) for item in cash["transactions"]] == [
        ("credit", 1000.0),
        ("debit", 75.1),
        ("debit", 50.25),
    ]
    assert [(item["direction"], item["amount"]) for item in cash["scheduled_cash_flows"]] == [
        ("income", 900.0),
        ("expense", 300.0),
    ]
    assert [item["contribution_id"] for item in savings["contributions"]] == [
        "contribution-old",
        "contribution-new",
    ]
    assert savings["goal"]["current_saved_amount"] == 350.0
    assert [item["transaction_id"] for item in anomalies["historical_transactions"]] == ["txn-old"]
    assert [item["transaction_id"] for item in anomalies["candidate_transactions"]] == [
        "txn-mid",
        "txn-new",
    ]
    for body in calls:
        UUID(body["request_id"])
        assert body["as_of"] == "2026-09-13T12:00:00Z"
        serialized = json.dumps(body).lower()
        assert "user_id" not in serialized
        assert "email" not in serialized
        assert "access_token" not in serialized
    assert database.requests
    assert all(str(request.scope.user_id) == USER_ID for request in database.requests)


@pytest.mark.asyncio
async def test_account_ownership_failure_stops_before_inference() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500, request=request)

    http_client = httpx.AsyncClient(
        base_url="https://models.test", transport=httpx.MockTransport(handler)
    )
    service = PredictionService(
        PredictionDatabase(owns_account=False),
        InferenceClient(_settings(), client=http_client),
        clock=lambda: AS_OF,
    )
    try:
        with pytest.raises(SafeMCPError) as caught:
            await service.forecast_recurring_charges(
                ForecastRecurringChargesRequest(
                    scope={"user_id": USER_ID}, account_id=OTHER_ACCOUNT_ID
                )
            )
    finally:
        await http_client.aclose()

    assert caught.value.code == "resource_not_found"
    assert called is False


def _cash_request() -> CashBalanceInferenceRequest:
    return CashBalanceInferenceRequest(
        request_id="55555555-5555-5555-5555-555555555555",
        as_of=AS_OF,
        currency="MXN",
        current_balance=100,
        horizon_days=7,
        transactions=[],
        scheduled_cash_flows=[],
    )


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "INFERENCE_AUTH_ERROR"),
        (403, "INFERENCE_AUTH_ERROR"),
        (409, "INFERENCE_VERSION_MISMATCH"),
        (422, "INFERENCE_CONTRACT_ERROR"),
        (500, "INFERENCE_UNAVAILABLE"),
        (503, "INFERENCE_UNAVAILABLE"),
    ],
)
@pytest.mark.asyncio
async def test_inference_http_failures_are_typed_and_sanitized(status: int, code: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": FAKE_KEY}}, request=request)

    http_client = httpx.AsyncClient(
        base_url="https://models.test", transport=httpx.MockTransport(handler)
    )
    client = InferenceClient(_settings(), client=http_client)
    try:
        with pytest.raises(SafeMCPError) as caught:
            await client.forecast_cash_balance(_cash_request())
    finally:
        await http_client.aclose()

    assert caught.value.code == code
    assert FAKE_KEY not in str(caught.value)


@pytest.mark.asyncio
async def test_timeout_and_network_failures_are_typed() -> None:
    for failure, expected in [
        (httpx.ReadTimeout(FAKE_KEY), "INFERENCE_TIMEOUT"),
        (httpx.ConnectError(FAKE_KEY), "INFERENCE_UNAVAILABLE"),
    ]:

        async def handler(request: httpx.Request, error: Exception = failure) -> httpx.Response:
            if isinstance(error, httpx.RequestError):
                error.request = request
            raise error

        http_client = httpx.AsyncClient(
            base_url="https://models.test", transport=httpx.MockTransport(handler)
        )
        client = InferenceClient(_settings(), client=http_client)
        try:
            with pytest.raises(SafeMCPError) as caught:
                await client.forecast_cash_balance(_cash_request())
        finally:
            await http_client.aclose()
        assert caught.value.code == expected
        assert FAKE_KEY not in str(caught.value)


@pytest.mark.asyncio
async def test_malformed_response_and_request_id_mismatch_are_rejected() -> None:
    for payload in [
        {"unexpected": True},
        _response(
            "/v1/predictions/cash-balance",
            {"request_id": "66666666-6666-6666-6666-666666666666"},
        ),
    ]:

        async def handler(request: httpx.Request, body: dict[str, Any] = payload) -> httpx.Response:
            return httpx.Response(200, json=body, request=request)

        http_client = httpx.AsyncClient(
            base_url="https://models.test", transport=httpx.MockTransport(handler)
        )
        client = InferenceClient(_settings(), client=http_client)
        try:
            with pytest.raises(SafeMCPError) as caught:
                await client.forecast_cash_balance(_cash_request())
        finally:
            await http_client.aclose()
        assert caught.value.code == "INFERENCE_RESPONSE_ERROR"


@pytest.mark.asyncio
async def test_secret_never_appears_in_tool_error_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=FAKE_KEY, request=request)

    http_client = httpx.AsyncClient(
        base_url="https://models.test", transport=httpx.MockTransport(handler)
    )
    database = PredictionDatabase()
    service = PredictionService(
        database, InferenceClient(_settings(), client=http_client), clock=lambda: AS_OF
    )
    context = SimpleNamespace(
        lifespan_context={"database": database, "predictions": service},
        request_context=None,
        origin_request_id="prediction-error",
    )
    caplog.set_level(logging.INFO, logger="supabase_mcp.tools.finance._shared")
    try:
        result = await forecast_cash_balance(
            ForecastCashBalanceRequest(scope={"user_id": USER_ID}, account_id=ACCOUNT_ID),
            context,
        )
    finally:
        await http_client.aclose()

    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "INFERENCE_AUTH_ERROR"
    assert FAKE_KEY not in json.dumps(result.structured_content)
    assert FAKE_KEY not in caplog.text


def test_inference_configuration_is_pairwise_and_secret_typed() -> None:
    settings = _settings()
    assert settings.inference_api_key is not None
    assert settings.inference_api_key.get_secret_value() == FAKE_KEY
    with pytest.raises(ValueError):
        Settings.model_validate(
            {
                "SUPABASE_DATABASE_URL": "postgresql://reader:placeholder@localhost/postgres",
                "INFERENCE_API_URL": "https://models.test",
            }
        )


def test_public_prediction_inputs_never_accept_raw_record_collections() -> None:
    for model in (
        ForecastCashBalanceRequest,
        PredictSavingsGoalRequest,
        ForecastRecurringChargesRequest,
        DetectTransactionAnomaliesRequest,
    ):
        fields = set(model.model_fields)
        assert fields.isdisjoint(
            {
                "transactions",
                "historical_transactions",
                "candidate_transactions",
                "scheduled_cash_flows",
                "contributions",
                "cash_flow_history",
            }
        )
