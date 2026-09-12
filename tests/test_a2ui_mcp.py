"""In-memory FastMCP protocol integration tests for A2UI discovery and calls."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from mcp.types import EmbeddedResource, TextContent, TextResourceContents

from supabase_mcp.a2ui_support.constants import A2UI_MIME_TYPE
from supabase_mcp.a2ui_support.surfaces import DATABASE_OVERVIEW_SURFACE
from supabase_mcp.server import mcp


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
        assert contents[0].mime_type == A2UI_MIME_TYPE
        template = json.loads(contents[0].text)
        assert "createSurface" in template[0]

        tools = await client.list_tools()
        tool = next(item for item in tools if item.name == "database_overview")
        assert tool.meta is not None
        assert tool.meta["ui"] == {
            "resourceUri": DATABASE_OVERVIEW_SURFACE.resource_uri,
            "mimeType": A2UI_MIME_TYPE,
        }
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True

        action_tool = next(item for item in tools if item.name == "a2ui_action")
        assert set(action_tool.input_schema["properties"]) == {
            "name",
            "surfaceId",
            "sourceComponentId",
            "timestamp",
            "context",
        }
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
