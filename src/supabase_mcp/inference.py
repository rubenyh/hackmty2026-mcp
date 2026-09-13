"""Shared, typed HTTP client for the stateless models service."""

from __future__ import annotations

from typing import TypeVar

import httpx
from pydantic import ValidationError

from supabase_mcp.config import Settings
from supabase_mcp.errors import SafeMCPError
from supabase_mcp.finance_models.predictions import (
    AnomalyDetectionInferenceRequest,
    AnomalyDetectionPredictionResponse,
    CashBalanceInferenceRequest,
    CashBalancePredictionResponse,
    PredictionResponse,
    RecurringChargesInferenceRequest,
    RecurringChargesPredictionResponse,
    SavingsGoalInferenceRequest,
    SavingsGoalPredictionResponse,
)

ResponseT = TypeVar("ResponseT", bound=PredictionResponse)


class InferenceClient:
    """Own one reusable AsyncClient and validate every prediction response."""

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None

    async def start(self) -> None:
        """Create the process-scoped HTTP client when inference is configured."""
        if self._client is not None or self._settings.inference_api_url is None:
            return
        timeout = httpx.Timeout(
            self._settings.inference_http_timeout_seconds,
            connect=self._settings.inference_connect_timeout_seconds,
        )
        self._client = httpx.AsyncClient(
            base_url=str(self._settings.inference_api_url),
            timeout=timeout,
        )

    async def stop(self) -> None:
        """Close only the HTTP client created by this instance."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
        self._client = None

    async def forecast_cash_balance(
        self, request: CashBalanceInferenceRequest
    ) -> CashBalancePredictionResponse:
        return await self._post(
            "/v1/predictions/cash-balance", request, CashBalancePredictionResponse
        )

    async def predict_savings_goal(
        self, request: SavingsGoalInferenceRequest
    ) -> SavingsGoalPredictionResponse:
        return await self._post(
            "/v1/predictions/savings-goal", request, SavingsGoalPredictionResponse
        )

    async def forecast_recurring_charges(
        self, request: RecurringChargesInferenceRequest
    ) -> RecurringChargesPredictionResponse:
        return await self._post(
            "/v1/predictions/recurring-charges", request, RecurringChargesPredictionResponse
        )

    async def detect_transaction_anomalies(
        self, request: AnomalyDetectionInferenceRequest
    ) -> AnomalyDetectionPredictionResponse:
        return await self._post(
            "/v1/predictions/anomalies", request, AnomalyDetectionPredictionResponse
        )

    async def _post(
        self,
        endpoint: str,
        request: CashBalanceInferenceRequest
        | SavingsGoalInferenceRequest
        | RecurringChargesInferenceRequest
        | AnomalyDetectionInferenceRequest,
        response_type: type[ResponseT],
    ) -> ResponseT:
        key = self._settings.inference_api_key
        if self._settings.inference_api_url is None or key is None or self._client is None:
            raise SafeMCPError(
                "INFERENCE_NOT_CONFIGURED",
                "The prediction service is not configured.",
            )

        try:
            response = await self._client.post(
                endpoint,
                headers={"Authorization": f"Bearer {key.get_secret_value()}"},
                json=request.model_dump(mode="json"),
            )
        except httpx.TimeoutException as exc:
            raise SafeMCPError("INFERENCE_TIMEOUT", "The prediction service timed out.") from exc
        except httpx.RequestError as exc:
            raise SafeMCPError(
                "INFERENCE_UNAVAILABLE", "The prediction service is unavailable."
            ) from exc

        if response.status_code in {401, 403}:
            raise SafeMCPError(
                "INFERENCE_AUTH_ERROR", "The prediction service rejected authentication."
            )
        if response.status_code == 409:
            raise SafeMCPError(
                "INFERENCE_VERSION_MISMATCH",
                "The deployed prediction model is incompatible.",
            )
        if response.status_code == 422:
            raise SafeMCPError(
                "INFERENCE_CONTRACT_ERROR", "The prediction request contract was rejected."
            )
        if response.status_code >= 500:
            raise SafeMCPError("INFERENCE_UNAVAILABLE", "The prediction service is unavailable.")
        if response.status_code < 200 or response.status_code >= 300:
            raise SafeMCPError(
                "INFERENCE_RESPONSE_ERROR", "The prediction service returned an unexpected error."
            )

        try:
            payload = response.json()
            validated = response_type.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            raise SafeMCPError(
                "INFERENCE_RESPONSE_ERROR", "The prediction response was malformed."
            ) from exc
        if validated.request_id != request.request_id:
            raise SafeMCPError(
                "INFERENCE_RESPONSE_ERROR", "The prediction response correlation was invalid."
            )
        return validated


__all__ = ["InferenceClient"]
