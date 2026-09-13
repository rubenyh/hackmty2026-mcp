"""In-memory FastMCP protocol integration tests for A2UI discovery and calls."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from mcp.types import EmbeddedResource, TextContent, TextResourceContents
from sqlalchemy.exc import SQLAlchemyError

import supabase_mcp.tools.a2ui as a2ui_tools
from supabase_mcp.a2ui_support.constants import A2UI_MIME_TYPE
from supabase_mcp.a2ui_support.surfaces import (
    CHAT_MESSAGE_SURFACE,
    DATA_CHART_SURFACE,
    DATABASE_OVERVIEW_SURFACE,
)
from supabase_mcp.a2ui_support.validation import A2UIValidator
from supabase_mcp.models import VisualizeAllowedDataResult
from supabase_mcp.server import mcp

USER_A = "68dc4d66-07b8-5893-95f1-07f06989a552"


async def test_a2ui_resource_and_tool_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SUPABASE_DATABASE_URL",
        "postgresql://reader:password@localhost/postgres?sslmode=require",
    )
    monkeypatch.setenv("MCP_ALLOWED_TABLES", "")

    async with Client(mcp) as client:
        resources = await client.list_resources()
        resource = next(
            item for item in resources if str(item.uri) == DATABASE_OVERVIEW_SURFACE.resource_uri
        )
        assert resource.mime_type == A2UI_MIME_TYPE

        contents = await client.read_resource(DATABASE_OVERVIEW_SURFACE.resource_uri)
        assert len(contents) == 1
        assert isinstance(contents[0], TextResourceContents)
        assert contents[0].mime_type == A2UI_MIME_TYPE
        template = json.loads(contents[0].text)
        A2UIValidator().validate_template(template, DATABASE_OVERVIEW_SURFACE)
        assert "createSurface" in template[0]

        chart_contents = await client.read_resource(DATA_CHART_SURFACE.resource_uri)
        assert len(chart_contents) == 1
        assert isinstance(chart_contents[0], TextResourceContents)
        chart_template = json.loads(chart_contents[0].text)
        A2UIValidator().validate_template(chart_template, DATA_CHART_SURFACE)
        assert chart_template[0]["createSurface"]["catalogId"] == DATA_CHART_SURFACE.catalog_id

        chat_contents = await client.read_resource(CHAT_MESSAGE_SURFACE.resource_uri)
        assert len(chat_contents) == 1
        assert isinstance(chat_contents[0], TextResourceContents)
        chat_template = json.loads(chat_contents[0].text)
        A2UIValidator().validate_template(chat_template, CHAT_MESSAGE_SURFACE)
        assert chat_template[0]["createSurface"]["catalogId"] == CHAT_MESSAGE_SURFACE.catalog_id

        for uri in (
            "a2ui://actions/inputs",
            "a2ui://actions/registry",
            "a2ui://actions/budget.create",
        ):
            contract = await client.read_resource(uri)
            assert json.loads(contract[0].text)
        tools = await client.list_tools()
        assert len(tools) == 26
        for listed_tool in tools:
            json.dumps(listed_tool.input_schema, allow_nan=False)
            assert listed_tool.input_schema.get("additionalProperties") is False
        tool = next(item for item in tools if item.name == "database_overview")
        assert tool.meta is not None
        assert tool.meta["ui"] == {
            "resourceUri": DATABASE_OVERVIEW_SURFACE.resource_uri,
            "mimeType": A2UI_MIME_TYPE,
        }
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True

        chart_tool = next(item for item in tools if item.name == "visualize_allowed_data")
        assert chart_tool.meta is not None
        assert chart_tool.meta["ui"] == {
            "resourceUri": DATA_CHART_SURFACE.resource_uri,
            "mimeType": A2UI_MIME_TYPE,
        }
        assert chart_tool.annotations is not None
        assert chart_tool.annotations.read_only_hint is True

        action_tool = next(item for item in tools if item.name == "a2ui_action")
        assert set(action_tool.input_schema["properties"]) == {
            "name",
            "surfaceId",
            "sourceComponentId",
            "timestamp",
            "context",
            "trustedScope",
            "actionProof",
        }
        assert action_tool.annotations is not None
        assert action_tool.annotations.read_only_hint is False
        assert set(action_tool.input_schema["required"]) == {
            "name",
            "surfaceId",
            "sourceComponentId",
            "timestamp",
            "context",
        }

        error_tool = next(item for item in tools if item.name == "a2ui_error")
        assert set(error_tool.input_schema["properties"]) == {
            "code",
            "surfaceId",
            "path",
            "message",
        }

        chat_tool = next(item for item in tools if item.name == "chat_message")
        assert chat_tool.meta is not None
        assert chat_tool.meta["ui"] == {
            "resourceUri": CHAT_MESSAGE_SURFACE.resource_uri,
            "mimeType": A2UI_MIME_TYPE,
        }
        assert chat_tool.annotations is not None
        assert chat_tool.annotations.read_only_hint is True

        chat_result = await client.call_tool(
            "chat_message", {"request": {"text": "  Hola, ¿en qué ayudo?  "}}
        )
        assert chat_result.is_error is not True
        embedded = next(item for item in chat_result.content if isinstance(item, EmbeddedResource))
        assert embedded.resource.mime_type == A2UI_MIME_TYPE
        update = json.loads(embedded.resource.text)[0]
        assert update["updateDataModel"]["value"]["message"] == "Hola, ¿en qué ayudo?"
        text_content = next(item for item in chat_result.content if isinstance(item, TextContent))
        assert text_content.text == "Hola, ¿en qué ayudo?"

        missing_scope = await client.call_tool(
            "select_rows",
            {"schema": "public", "table": "transactions"},
            raise_on_error=False,
        )
        assert missing_scope.is_error is True

        result = await client.call_tool("database_overview", {"limit": 5})
        assert result.structured_content is not None
        assert result.structured_content["ok"] is True
        assert result.meta is not None
        assert result.meta["ui"] == tool.meta["ui"]
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text
        embedded = next(item for item in result.content if isinstance(item, EmbeddedResource))
        assert isinstance(embedded.resource, TextResourceContents)
        assert embedded.resource.mime_type == A2UI_MIME_TYPE
        dynamic_messages = json.loads(embedded.resource.text)
        assert "updateDataModel" in dynamic_messages[0]

        # A non-A2UI client can ignore EmbeddedResource and still use these values.
        assert result.content[0].text
        assert result.structured_content["object_count"] == 0

        async def fake_chart(_database: object, request: object) -> VisualizeAllowedDataResult:
            return VisualizeAllowedDataResult.model_validate(
                {
                    "ok": True,
                    "source": {"schema": "public", "table": "cashflow"},
                    "row_count": 0,
                    "omitted_null_rows": 0,
                    "limit": 10,
                    "truncated": False,
                    "chart": {
                        "kind": "area",
                        "accessibleSummary": "Area chart with no data.",
                        "props": {
                            "data": [],
                            "series": [{"id": "series_1", "label": "income"}],
                        },
                    },
                }
            )

        monkeypatch.setattr(a2ui_tools, "get_data_chart", fake_chart)
        chart_result = await client.call_tool(
            "visualize_allowed_data",
            {
                "request": {
                    "scope": {"user_id": USER_A},
                    "source": {"schema": "public", "table": "cashflow"},
                    "limit": 10,
                    "visualization": {
                        "kind": "area",
                        "x_column": "month",
                        "y_columns": ["income"],
                    },
                }
            },
        )
        assert chart_result.meta is not None
        assert chart_result.meta["ui"] == chart_tool.meta["ui"]
        assert chart_result.structured_content is not None
        assert chart_result.structured_content["ok"] is True
        chart_embedded = next(
            item for item in chart_result.content if isinstance(item, EmbeddedResource)
        )
        assert isinstance(chart_embedded.resource, TextResourceContents)
        chart_dynamic = json.loads(chart_embedded.resource.text)
        assert len(chart_dynamic) == 1
        assert set(chart_dynamic[0]) == {"version", "updateDataModel"}

        async def failing_chart(_database: object, _request: object) -> VisualizeAllowedDataResult:
            raise SQLAlchemyError("private SQL detail")

        monkeypatch.setattr(a2ui_tools, "get_data_chart", failing_chart)
        failed_chart = await client.call_tool(
            "visualize_allowed_data",
            {
                "request": {
                    "scope": {"user_id": USER_A},
                    "source": {"schema": "public", "table": "cashflow"},
                    "visualization": {
                        "kind": "area",
                        "x_column": "month",
                        "y_columns": ["income"],
                    },
                }
            },
            raise_on_error=False,
        )
        assert failed_chart.is_error is True
        assert failed_chart.structured_content == {
            "ok": False,
            "error": {
                "code": "database_error",
                "message": "The database request could not be completed.",
            },
        }
        assert "private SQL detail" not in str(failed_chart)
