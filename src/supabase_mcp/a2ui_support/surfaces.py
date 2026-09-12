"""Central, validated registry of packaged A2UI surfaces."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

from supabase_mcp.a2ui_support.constants import (
    A2UI_BASIC_CATALOG,
    A2UI_FINANCE_CATALOG,
    A2UI_FINANCE_V2_CATALOG,
    CHAT_MESSAGE_RESOURCE_URI,
    CHAT_MESSAGE_SURFACE_ID,
    DATA_CHART_RESOURCE_URI,
    DATA_CHART_SURFACE_ID,
    DATABASE_OVERVIEW_RESOURCE_URI,
    DATABASE_OVERVIEW_SURFACE_ID,
    FINANCIAL_VIEW_RESOURCE_URI,
    FINANCIAL_VIEW_SURFACE_ID,
)
from supabase_mcp.a2ui_support.models import SurfaceSpec
from supabase_mcp.a2ui_support.validation import A2UIValidationError, A2UIValidator


class SurfaceRegistry:
    """Register immutable A2UI templates and reject ambiguous identifiers."""

    def __init__(self, validator: A2UIValidator) -> None:
        self._validator = validator
        self._by_id: dict[str, SurfaceSpec] = {}
        self._by_uri: dict[str, SurfaceSpec] = {}
        self._templates: dict[str, tuple[dict[str, Any], ...]] = {}
        self._serialized: dict[str, str] = {}

    def register(self, surface: SurfaceSpec) -> None:
        if surface.surface_id in self._by_id:
            raise A2UIValidationError(f"Duplicate A2UI surface ID: {surface.surface_id}")
        if surface.resource_uri in self._by_uri:
            raise A2UIValidationError(f"Duplicate A2UI resource URI: {surface.resource_uri}")

        template_file = files("supabase_mcp.a2ui_support.templates").joinpath(surface.template_name)
        if not template_file.is_file():
            raise A2UIValidationError(f"A2UI template does not exist: {surface.template_name}")
        try:
            raw = json.loads(template_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise A2UIValidationError("A2UI template could not be loaded") from exc
        if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
            raise A2UIValidationError("A2UI template must be a JSON array of messages")

        messages = tuple(dict(item) for item in raw)
        self._validator.validate_template(messages, surface)
        self._by_id[surface.surface_id] = surface
        self._by_uri[surface.resource_uri] = surface
        self._templates[surface.surface_id] = messages
        self._serialized[surface.surface_id] = json.dumps(
            messages, ensure_ascii=False, separators=(",", ":")
        )

    def get_by_id(self, surface_id: str) -> SurfaceSpec | None:
        return self._by_id.get(surface_id)

    def get_by_uri(self, resource_uri: str) -> SurfaceSpec | None:
        return self._by_uri.get(resource_uri)

    def template(self, surface: SurfaceSpec) -> tuple[dict[str, Any], ...]:
        return self._templates[surface.surface_id]

    def serialized_template(self, surface: SurfaceSpec) -> str:
        return self._serialized[surface.surface_id]


DATABASE_OVERVIEW_SURFACE = SurfaceSpec(
    surface_id=DATABASE_OVERVIEW_SURFACE_ID,
    resource_uri=DATABASE_OVERVIEW_RESOURCE_URI,
    catalog_id=A2UI_BASIC_CATALOG,
    template_name="database_overview.json",
    title="Database overview",
    description="Static A2UI layout for a bounded list of allowlisted database objects.",
)

DATA_CHART_SURFACE = SurfaceSpec(
    surface_id=DATA_CHART_SURFACE_ID,
    resource_uri=DATA_CHART_RESOURCE_URI,
    catalog_id=A2UI_FINANCE_CATALOG,
    template_name="data_chart.json",
    title="Data chart",
    description="Static A2UI layout for a bounded chart of allowlisted database data.",
)

CHAT_MESSAGE_SURFACE = SurfaceSpec(
    surface_id=CHAT_MESSAGE_SURFACE_ID,
    resource_uri=CHAT_MESSAGE_RESOURCE_URI,
    catalog_id=A2UI_BASIC_CATALOG,
    template_name="chat_message.json",
    title="Chat message",
    description="Static A2UI layout wrapping one plain conversational reply as a text surface.",
)

FINANCIAL_VIEW_SURFACE = SurfaceSpec(
    surface_id=FINANCIAL_VIEW_SURFACE_ID,
    resource_uri=FINANCIAL_VIEW_RESOURCE_URI,
    catalog_id=A2UI_FINANCE_V2_CATALOG,
    template_name="financial_view.json",
    title="Financial view",
    description=(
        "Stable Finance v2 surface composed from one semantic BankingView and one request action."
    ),
)

SURFACE_REGISTRY = SurfaceRegistry(A2UIValidator())
SURFACE_REGISTRY.register(DATABASE_OVERVIEW_SURFACE)
SURFACE_REGISTRY.register(DATA_CHART_SURFACE)
SURFACE_REGISTRY.register(CHAT_MESSAGE_SURFACE)
SURFACE_REGISTRY.register(FINANCIAL_VIEW_SURFACE)
