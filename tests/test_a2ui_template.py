"""Validation and packaging checks for the static A2UI surface."""

from __future__ import annotations

import tarfile
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from hatchling.build import build_sdist, build_wheel

from supabase_mcp.a2ui_support.catalog_registry import (
    CATALOG_REGISTRY,
    CatalogRegistrationError,
    CatalogRegistry,
)
from supabase_mcp.a2ui_support.constants import (
    A2UI_BASIC_CATALOG,
    A2UI_FINANCE_CATALOG,
    A2UI_FINANCE_V2_CATALOG,
    A2UI_VERSION,
)
from supabase_mcp.a2ui_support.mappers import database_overview_data_model
from supabase_mcp.a2ui_support.surfaces import (
    DATA_CHART_SURFACE,
    DATABASE_OVERVIEW_SURFACE,
    FINANCIAL_VIEW_SURFACE,
    SURFACE_REGISTRY,
)
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
        assert "supabase_mcp/a2ui_support/templates/database_overview.json" in wheel.namelist()
        assert "supabase_mcp/a2ui_support/templates/data_chart.json" in wheel.namelist()
        assert "supabase_mcp/a2ui_support/catalogs/finance_v1.json" in wheel.namelist()
        assert "supabase_mcp/a2ui_support/catalogs/banking_view.schema.json" in wheel.namelist()
        assert "supabase_mcp/a2ui_support/templates/financial_view.json" in wheel.namelist()


def test_finance_catalog_and_chart_template_are_valid() -> None:
    schema = CATALOG_REGISTRY.schema(A2UI_FINANCE_CATALOG)
    assert schema is not None
    assert schema["catalogId"] == A2UI_FINANCE_CATALOG
    assert set(schema["components"]) == {"Text", "Button", "Card", "Column", "Chart"}

    messages = SURFACE_REGISTRY.template(DATA_CHART_SURFACE)
    assert messages[0]["createSurface"]["catalogId"] == A2UI_FINANCE_CATALOG
    assert [next(key for key in message if key != "version") for message in messages] == [
        "createSurface",
        "updateComponents",
    ]
    components = messages[1]["updateComponents"]["components"]
    assert {component["component"] for component in components} == {
        "Text",
        "Card",
        "Column",
        "Chart",
    }

    finance_v2 = CATALOG_REGISTRY.schema(A2UI_FINANCE_V2_CATALOG)
    assert finance_v2 is not None
    assert set(finance_v2["components"]) == {
        "Text",
        "Button",
        "Card",
        "Column",
        "Chart",
        "TextField",
        "DateTimeInput",
        "Slider",
        "BankingView",
    }
    financial_components = SURFACE_REGISTRY.template(FINANCIAL_VIEW_SURFACE)[1]["updateComponents"][
        "components"
    ]
    assert [component["id"] for component in financial_components] == [
        "root",
        "banking_view",
        "request_financial_view_label",
        "request_financial_view_button",
    ]
    assert {component["component"] for component in financial_components} == {
        "Column",
        "BankingView",
        "Text",
        "Button",
    }


def test_duplicate_and_unknown_catalogs_are_rejected() -> None:
    registry = CatalogRegistry()
    registry.register_basic()
    with pytest.raises(CatalogRegistrationError, match="Duplicate"):
        registry.register_basic()
    with pytest.raises(CatalogRegistrationError, match="Unknown"):
        registry.validator("https://example.invalid/catalog")


def test_catalog_and_template_are_in_sdist(tmp_path: Path) -> None:
    archive_name = build_sdist(str(tmp_path))
    with tarfile.open(tmp_path / archive_name, "r:gz") as archive:
        names = archive.getnames()
        assert any(name.endswith("/a2ui_support/catalogs/finance_v1.json") for name in names)
        assert any(
            name.endswith("/a2ui_support/catalogs/banking_view.schema.json") for name in names
        )
        assert any(name.endswith("/a2ui_support/templates/data_chart.json") for name in names)
        assert any(name.endswith("/a2ui_support/templates/financial_view.json") for name in names)
