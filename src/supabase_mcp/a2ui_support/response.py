"""Reusable construction of validated A2UI MCP tool results."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fastmcp.tools import ToolResult
from mcp.types import Annotations, EmbeddedResource, TextContent, TextResourceContents

from supabase_mcp.a2ui_support.constants import A2UI_MIME_TYPE, A2UI_VERSION
from supabase_mcp.a2ui_support.models import SurfaceSpec
from supabase_mcp.a2ui_support.validation import A2UIValidationError, A2UIValidator
from supabase_mcp.serialization import to_json_safe


def ui_metadata(surface: SurfaceSpec) -> dict[str, dict[str, str]]:
    """Build the static/runtime MCP metadata link for one A2UI surface."""
    return {
        "ui": {
            "resourceUri": surface.resource_uri,
            "mimeType": A2UI_MIME_TYPE,
        }
    }


class A2UIResponseFactory:
    """Compose domain data, fallback text, and a validated A2UI data update."""

    def __init__(self, surface: SurfaceSpec, validator: A2UIValidator | None = None) -> None:
        self.surface = surface
        self._validator = validator or A2UIValidator()

    def update_data_model(self, value: Any, path: str = "/") -> dict[str, Any]:
        """Create a validated, detached updateDataModel message."""
        self._validator.validate_json_pointer(path)
        safe_value = to_json_safe(value)
        try:
            json.dumps(safe_value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise A2UIValidationError("A2UI data model must be JSON serializable") from exc
        message = {
            "version": A2UI_VERSION,
            "updateDataModel": {
                "surfaceId": self.surface.surface_id,
                "path": path,
                "value": safe_value,
            },
        }
        self._validator.validate_message(message, self.surface)
        return message

    def build(
        self,
        *,
        fallback_text: str,
        data_model: Mapping[str, Any],
        structured_content: Mapping[str, Any] | None = None,
        path: str = "/",
    ) -> ToolResult:
        """Return a complete MCP result for both A2UI and non-A2UI clients."""
        if not fallback_text.strip():
            raise A2UIValidationError("A2UI fallback text must not be empty")
        update = self.update_data_model(data_model, path)
        structured_source = structured_content if structured_content is not None else data_model
        structured = to_json_safe(structured_source)
        if not isinstance(structured, dict):
            raise A2UIValidationError("A2UI structured content must be an object")
        return ToolResult(
            content=[
                TextContent(text=fallback_text),
                EmbeddedResource(
                    resource=TextResourceContents(
                        uri=f"{self.surface.resource_uri}/data",
                        mime_type=A2UI_MIME_TYPE,
                        text=json.dumps([update], ensure_ascii=False, separators=(",", ":")),
                    ),
                    annotations=Annotations(audience=["user"]),
                ),
            ],
            structured_content=structured,
            meta=ui_metadata(self.surface),
        )
