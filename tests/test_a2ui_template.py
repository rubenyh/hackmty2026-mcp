"""Validation and packaging checks for the static A2UI surface."""

from __future__ import annotations

import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hatchling.build import build_wheel

from supabase_mcp.a2ui.constants import A2UI_BASIC_CATALOG, A2UI_VERSION
from supabase_mcp.a2ui.mappers import database_overview_data_model
from supabase_mcp.a2ui.surfaces import DATABASE_OVERVIEW_SURFACE, SURFACE_REGISTRY
from supabase_mcp.models import AllowedObject
from supabase_mcp.services.database_overview import DatabaseOverview


def _paths(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        found = {value["path"]} if isinstance(value.get("path"), str) else set()
        for item in value.values():
            found.update(_paths(item))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for item in value:
            found.update(_paths(item))
        return found
    return set()


def test_database_overview_template_is_valid_and_bound() -> None:
    messages = SURFACE_REGISTRY.template(DATABASE_OVERVIEW_SURFACE)
    assert len(messages) == 2
    assert "createSurface" in messages[0]
    assert "updateComponents" in messages[1]
    assert all(message["version"] == A2UI_VERSION for message in messages)
    assert messages[0]["createSurface"]["catalogId"] == A2UI_BASIC_CATALOG

    components = messages[1]["updateComponents"]["components"]
    ids = [component["id"] for component in components]
    assert "root" in ids
    assert len(ids) == len(set(ids))

    sample = DatabaseOverview(
        objects=(AllowedObject(schema="public", table="customers", kind="table"),),
        total_count=1,
        limit=50,
        truncated=False,
    )
    data_model = database_overview_data_model(sample)
    bound_roots = {path.split("/", 2)[1] for path in _paths(messages) if path.startswith("/")}
    assert bound_roots <= data_model.keys()


def test_database_overview_template_is_in_wheel(tmp_path: Path) -> None:
    wheel_name = build_wheel(str(tmp_path))
    with zipfile.ZipFile(tmp_path / wheel_name) as wheel:
        assert "supabase_mcp/a2ui/templates/database_overview.json" in wheel.namelist()
