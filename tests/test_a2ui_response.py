"""Unit tests for reusable A2UI response composition."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from mcp.types import EmbeddedResource, TextContent, TextResourceContents

from supabase_mcp.a2ui_support.constants import A2UI_MIME_TYPE, A2UI_VERSION
from supabase_mcp.a2ui_support.response import A2UIResponseFactory
from supabase_mcp.a2ui_support.surfaces import DATA_CHART_SURFACE, DATABASE_OVERVIEW_SURFACE
from supabase_mcp.a2ui_support.validation import A2UIValidationError


def test_response_factory_builds_complete_non_mutating_result() -> None:
    factory = A2UIResponseFactory(DATABASE_OVERVIEW_SURFACE)
    data_model = {"title": "Overview", "items": [{"name": "customers"}]}
    original = deepcopy(data_model)

    result = factory.build(
        fallback_text="One allowlisted table: public.customers.",
        data_model=data_model,
        structured_content={"ok": True, "objects": [{"table": "customers"}]},
    )

    assert data_model == original
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text.startswith("One allowlisted table")
    assert isinstance(result.content[1], EmbeddedResource)
    embedded = result.content[1]
    assert embedded.annotations is not None
    assert embedded.annotations.audience == ["user"]
    assert isinstance(embedded.resource, TextResourceContents)
    assert embedded.resource.mime_type == A2UI_MIME_TYPE
    payload = json.loads(embedded.resource.text)
    assert payload == [
        {
            "version": A2UI_VERSION,
            "updateDataModel": {
                "surfaceId": DATABASE_OVERVIEW_SURFACE.surface_id,
                "path": "/",
                "value": data_model,
            },
        }
    ]
    assert result.structured_content == {"ok": True, "objects": [{"table": "customers"}]}
    assert result.meta == {
        "ui": {
            "resourceUri": DATABASE_OVERVIEW_SURFACE.resource_uri,
            "mimeType": A2UI_MIME_TYPE,
        }
    }


@pytest.mark.parametrize("path", ["relative", "/bad~escape", "#/fragment"])
def test_response_factory_rejects_invalid_paths(path: str) -> None:
    factory = A2UIResponseFactory(DATABASE_OVERVIEW_SURFACE)
    with pytest.raises(A2UIValidationError):
        factory.update_data_model({"title": "Overview"}, path=path)


def test_response_factory_accepts_specific_json_pointer() -> None:
    factory = A2UIResponseFactory(DATABASE_OVERVIEW_SURFACE)
    message = factory.update_data_model("Updated", path="/summary")
    assert message["updateDataModel"]["path"] == "/summary"


def test_response_factory_rejects_non_json_float() -> None:
    factory = A2UIResponseFactory(DATABASE_OVERVIEW_SURFACE)
    with pytest.raises(A2UIValidationError):
        factory.update_data_model({"value": float("nan")})


def test_chart_response_contains_only_dynamic_update_and_keeps_fallbacks() -> None:
    result = A2UIResponseFactory(DATA_CHART_SURFACE).build(
        fallback_text="Area chart with no data.",
        data_model={
            "title": "Cash flow",
            "summary": "Area chart with no data.",
            "chart": {
                "kind": "area",
                "accessibleSummary": "Area chart with no data.",
                "props": {
                    "data": [],
                    "series": [{"id": "income", "label": "income"}],
                },
            },
        },
        structured_content={"ok": True, "row_count": 0},
    )
    assert isinstance(result.content[0], TextContent)
    embedded = result.content[1]
    assert isinstance(embedded, EmbeddedResource)
    assert isinstance(embedded.resource, TextResourceContents)
    messages = json.loads(embedded.resource.text)
    assert len(messages) == 1
    assert set(messages[0]) == {"version", "updateDataModel"}
    assert result.structured_content == {"ok": True, "row_count": 0}
    assert result.meta == {
        "ui": {"resourceUri": DATA_CHART_SURFACE.resource_uri, "mimeType": A2UI_MIME_TYPE}
    }
