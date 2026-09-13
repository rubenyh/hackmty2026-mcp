"""Focused Finance v2 schema, surface, and action-contract tests."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from supabase_mcp.a2ui_support.actions import ActionDispatchError
from supabase_mcp.a2ui_support.catalog_registry import CATALOG_REGISTRY
from supabase_mcp.a2ui_support.constants import (
    A2UI_FINANCE_V2_CATALOG,
    FINANCIAL_VIEW_SURFACE_ID,
    PRESENT_FINANCIAL_VIEW_ACTION,
    PRESENT_FINANCIAL_VIEW_COMPONENT_ID,
)
from supabase_mcp.a2ui_support.validation import A2UIValidationError, A2UIValidator
from supabase_mcp.config import Settings
from supabase_mcp.database import DatabaseClient
from supabase_mcp.models import FinancialIntent, FinancialSurfaceRequest
from supabase_mcp.tools.a2ui import ACTION_REGISTRY, present_financial_view

USER_ID = "11111111-1111-4111-8111-111111111111"


def _database() -> DatabaseClient:
    return DatabaseClient(
        Settings(
            SUPABASE_DATABASE_URL=SecretStr(
                "postgresql://reader:password@localhost/postgres?sslmode=require"
            ),
            MCP_ALLOWED_TABLES="",
        )
    )


def _empty_view() -> dict[str, object]:
    return {
        "title": "No transactions",
        "intent": "transactions",
        "state": "empty",
        "description": "No transactions matched the selected period.",
    }


def _payment_card() -> dict[str, object]:
    return {
        "cardId": "card-1",
        "cardName": "Tarjeta Oro",
        "cardType": "credit",
        "network": "mastercard",
        "lastFour": "9012",
        "status": "active",
        "expires": "2028-11",
        "accountId": "account-credit",
    }


def _summary_view() -> dict[str, object]:
    return {
        "title": "Tu panorama financiero",
        "intent": "financial-summary",
        "currency": "MXN",
        "totalOwnedBalance": 20500,
        "accounts": [
            {
                "accountId": "account-credit",
                "accountName": "Tarjeta de credito",
                "accountType": "credit",
                "availableBalance": 1500,
            }
        ],
        "cards": [_payment_card()],
    }


def _credit_card_view() -> dict[str, object]:
    card = dict(_payment_card())
    card.pop("accountId")
    return {
        "title": "Organiza el pago de tu tarjeta",
        "intent": "credit-card",
        "currency": "MXN",
        "cardName": "Tarjeta Oro",
        "lastFour": "9012",
        "card": card,
        "debt": 8500,
        "creditLimit": 10000,
        "statementBalance": 6200,
        "availableCredit": 1500,
        "minimumPayment": 420,
        "interestFreePayment": 6200,
        "cutoffDate": "2026-09-10",
        "dueDate": "2026-09-25",
        "annualInterestRate": 36.9,
        "catPercentage": 48.2,
    }


def test_valid_finance_v2_banking_view_passes() -> None:
    A2UIValidator().validate_banking_view(_empty_view())


@pytest.mark.parametrize("view", [_summary_view(), _credit_card_view()])
def test_payment_card_and_credit_terms_validate(view: dict[str, object]) -> None:
    """A balance question carries card faces; a card question carries its terms."""
    A2UIValidator().validate_banking_view(view)


@pytest.mark.parametrize(
    "card_override",
    [
        {"lastFour": "12"},
        {"lastFour": "4111111111111111"},
        {"network": "discover"},
        {"cardType": "prepaid"},
        {"expires": "2028-13"},
        {"expires": "2028-11-04"},
        {"pan": "4111111111111111"},
        {"cvv": "123"},
    ],
)
def test_payment_card_rejects_malformed_and_sensitive_fields(
    card_override: dict[str, object],
) -> None:
    view = _summary_view()
    with pytest.raises(A2UIValidationError):
        A2UIValidator().validate_banking_view(
            {**view, "cards": [{**_payment_card(), **card_override}]}
        )


@pytest.mark.parametrize("removed", ["totalOwnedBalance", "accounts"])
def test_financial_summary_requires_the_backend_computed_total(removed: str) -> None:
    view = _summary_view()
    view.pop(removed)
    with pytest.raises(A2UIValidationError):
        A2UIValidator().validate_banking_view(view)


@pytest.mark.parametrize(
    "override",
    [
        {"annualInterestRate": -1},
        {"annualInterestRate": 1001},
        {"catPercentage": "48.2%"},
        {"creditLimit": 0},
        {"statementBalance": -100},
        {"card": {**_payment_card(), "brandColor": "#ff0000"}},
    ],
)
def test_credit_card_terms_stay_bounded(override: dict[str, object]) -> None:
    with pytest.raises(A2UIValidationError):
        A2UIValidator().validate_banking_view({**_credit_card_view(), **override})


def test_canonical_schema_contains_exact_intent_parity_set() -> None:
    catalog = CATALOG_REGISTRY.schema(A2UI_FINANCE_V2_CATALOG)
    assert catalog is not None
    view_schema = catalog["components"]["BankingView"]["allOf"][2]["properties"]["view"]["oneOf"][1]
    ready_intents = {
        item["properties"]["intent"]["const"] for item in view_schema["anyOf"][0]["oneOf"]
    }
    empty_intents = set(view_schema["anyOf"][1]["properties"]["intent"]["enum"])
    expected = {intent.value for intent in FinancialIntent}
    assert ready_intents == expected
    assert empty_intents == expected


@pytest.mark.parametrize(
    "view",
    [
        {"title": "Invalid", "intent": "unknown", "state": "empty", "description": "x"},
        {"title": "Missing data", "intent": "transactions"},
        {**_empty_view(), "backgroundColor": "#ffffff"},
    ],
)
def test_invalid_banking_view_intent_data_and_style_fail(view: dict[str, object]) -> None:
    with pytest.raises(A2UIValidationError):
        A2UIValidator().validate_banking_view(view)


async def test_generic_financial_surface_builds_valid_composed_result() -> None:
    result = await present_financial_view(
        FinancialSurfaceRequest(
            view=_empty_view(),
            actionLabel="Show this month",
            requestIntent="transactions",
        )
    )
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["surfaceId"] == FINANCIAL_VIEW_SURFACE_ID
    assert result.structured_content["view"] == _empty_view()


async def test_request_financial_view_normalizes_bounded_context_and_scope() -> None:
    result = await ACTION_REGISTRY.dispatch(
        name=PRESENT_FINANCIAL_VIEW_ACTION,
        surface_id=FINANCIAL_VIEW_SURFACE_ID,
        source_component_id=PRESENT_FINANCIAL_VIEW_COMPONENT_ID,
        timestamp="2026-09-12T12:00:00Z",
        context={
            "intent": "transactions",
            "accountId": "checking-1",
            "startDate": "2026-09-01",
            "endDate": "2026-09-12",
            "period": "month-to-date",
        },
        trusted_scope={"user_id": USER_ID},
        database=_database(),
    )
    assert result.structured_content is not None
    assert result.structured_content["request"] == {
        "intent": "transactions",
        "accountId": "checking-1",
        "startDate": "2026-09-01",
        "endDate": "2026-09-12",
        "period": "month-to-date",
    }
    assert "user_id" not in result.structured_content["action"]["context"]
    assert result.structured_content["trustedScope"] == {"user_id": USER_ID}


async def test_identity_in_financial_action_context_is_rejected() -> None:
    with pytest.raises(ActionDispatchError) as captured:
        await ACTION_REGISTRY.dispatch(
            name=PRESENT_FINANCIAL_VIEW_ACTION,
            surface_id=FINANCIAL_VIEW_SURFACE_ID,
            source_component_id=PRESENT_FINANCIAL_VIEW_COMPONENT_ID,
            timestamp="2026-09-12T12:00:00Z",
            context={"intent": "transactions", "user_id": USER_ID},
            trusted_scope={"user_id": USER_ID},
            database=_database(),
        )
    assert captured.value.code == "invalid_action_context"


async def test_financial_action_requires_separate_trusted_scope() -> None:
    with pytest.raises(ActionDispatchError) as captured:
        await ACTION_REGISTRY.dispatch(
            name=PRESENT_FINANCIAL_VIEW_ACTION,
            surface_id=FINANCIAL_VIEW_SURFACE_ID,
            source_component_id=PRESENT_FINANCIAL_VIEW_COMPONENT_ID,
            timestamp="2026-09-12T12:00:00Z",
            context={"intent": "transactions"},
            database=_database(),
        )
    assert captured.value.code == "missing_trusted_scope"
