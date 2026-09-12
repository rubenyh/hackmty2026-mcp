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


def test_valid_finance_v2_banking_view_passes() -> None:
    A2UIValidator().validate_banking_view(_empty_view())


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
