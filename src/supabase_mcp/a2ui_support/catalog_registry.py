"""Validated allowlist and cache for supported A2UI catalogs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from importlib.resources import files
from typing import Any

from a2ui.basic_catalog.provider import BasicCatalog  # type: ignore[import-untyped]
from a2ui.inference_formats.direct_json import DirectJsonFormat  # type: ignore[import-untyped]
from a2ui.schema.catalog import CatalogConfig  # type: ignore[import-untyped]
from a2ui.schema.catalog_provider import A2uiCatalogProvider  # type: ignore[import-untyped]

from supabase_mcp.a2ui_support.constants import (
    A2UI_BASIC_CATALOG,
    A2UI_FINANCE_CATALOG,
    A2UI_FINANCE_V2_CATALOG,
    A2UI_SDK_VERSION,
    A2UI_VERSION,
)


class CatalogRegistrationError(ValueError):
    """A packaged catalog is missing, malformed, duplicated, or invalid."""


class _MappingCatalogProvider(A2uiCatalogProvider):  # type: ignore[misc]
    def __init__(self, catalog: Mapping[str, Any]) -> None:
        self._catalog = deepcopy(dict(catalog))

    def load(self) -> dict[str, Any]:
        return deepcopy(self._catalog)


class CatalogRegistry:
    """Load each allowlisted catalog once and cache its official SDK validator."""

    def __init__(self) -> None:
        self._validators: dict[str, Any] = {}
        self._schemas: dict[str, dict[str, Any] | None] = {}

    def register_basic(self, catalog_id: str = A2UI_BASIC_CATALOG) -> None:
        self._register(catalog_id, BasicCatalog.get_config(A2UI_SDK_VERSION), None)

    def register_packaged(
        self,
        *,
        catalog_id: str,
        package: str,
        resource_name: str,
        name: str,
    ) -> None:
        resource = files(package).joinpath(resource_name)
        if not resource.is_file():
            raise CatalogRegistrationError("A packaged A2UI catalog is missing")
        try:
            loaded = json.loads(resource.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogRegistrationError("A packaged A2UI catalog could not be loaded") from exc
        if not isinstance(loaded, Mapping):
            raise CatalogRegistrationError("A packaged A2UI catalog must be an object")
        schema = dict(loaded)
        if schema.get("catalogId") != catalog_id or schema.get("$id") != catalog_id:
            raise CatalogRegistrationError("A packaged A2UI catalog has an unexpected identifier")
        config = CatalogConfig(name=name, provider=_MappingCatalogProvider(schema))
        self._register(catalog_id, config, schema)

    def register_finance_v2(self) -> None:
        """Build Finance v2 from Finance v1 plus the canonical BankingView schema."""
        base = self._load_packaged_json("finance_v1.json")
        banking_view = self._load_packaged_json("banking_view.schema.json")
        banking_view.pop("$schema", None)
        banking_view.pop("$id", None)

        schema = deepcopy(base)
        schema["$id"] = A2UI_FINANCE_V2_CATALOG
        schema["catalogId"] = A2UI_FINANCE_V2_CATALOG
        schema["title"] = "Fluidbank Finance Catalog v2"
        schema["description"] = "A bounded A2UI v0.9.1 catalog for semantic financial surfaces."
        schema["components"]["BankingView"] = {
            "type": "object",
            "allOf": [
                {
                    "$ref": (
                        "https://a2ui.org/specification/v0_9/common_types.json"
                        "#/$defs/ComponentCommon"
                    )
                },
                {"$ref": "#/$defs/CatalogComponentCommon"},
                {
                    "type": "object",
                    "properties": {
                        "component": {"const": "BankingView"},
                        "view": {
                            "oneOf": [
                                {"$ref": "#/$defs/DataBinding"},
                                banking_view,
                            ]
                        },
                    },
                    "required": ["component", "view"],
                },
            ],
            "unevaluatedProperties": False,
        }
        schema["$defs"]["anyComponent"]["oneOf"].append({"$ref": "#/components/BankingView"})
        config = CatalogConfig(
            name="fluidbank-finance-v2",
            provider=_MappingCatalogProvider(schema),
        )
        self._register(A2UI_FINANCE_V2_CATALOG, config, schema)

    @staticmethod
    def _load_packaged_json(resource_name: str) -> dict[str, Any]:
        resource = files("supabase_mcp.a2ui_support.catalogs").joinpath(resource_name)
        if not resource.is_file():
            raise CatalogRegistrationError("A packaged A2UI catalog is missing")
        try:
            loaded = json.loads(resource.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogRegistrationError("A packaged A2UI catalog could not be loaded") from exc
        if not isinstance(loaded, Mapping):
            raise CatalogRegistrationError("A packaged A2UI catalog must be an object")
        return dict(loaded)

    def _register(
        self,
        catalog_id: str,
        config: CatalogConfig,
        schema: dict[str, Any] | None,
    ) -> None:
        if catalog_id in self._validators:
            raise CatalogRegistrationError("Duplicate A2UI catalog identifier")
        try:
            catalog = DirectJsonFormat(
                version=A2UI_SDK_VERSION,
                catalogs=[config],
                accepts_inline_catalogs=False,
            ).get_selected_catalog()
            validator = catalog.validator
            validator.validate(
                [
                    {
                        "version": A2UI_VERSION,
                        "createSurface": {
                            "surfaceId": "catalog-validation",
                            "catalogId": catalog_id,
                        },
                    },
                    {
                        "version": A2UI_VERSION,
                        "updateComponents": {
                            "surfaceId": "catalog-validation",
                            "components": [
                                {"id": "root", "component": "Text", "text": "validation"}
                            ],
                        },
                    },
                ]
            )
        except Exception as exc:
            raise CatalogRegistrationError("An A2UI catalog failed validation") from exc
        self._validators[catalog_id] = validator
        self._schemas[catalog_id] = deepcopy(schema)

    def validator(self, catalog_id: str) -> Any:
        validator = self._validators.get(catalog_id)
        if validator is None:
            raise CatalogRegistrationError("Unknown A2UI catalog identifier")
        return validator

    def schema(self, catalog_id: str) -> dict[str, Any] | None:
        if catalog_id not in self._schemas:
            raise CatalogRegistrationError("Unknown A2UI catalog identifier")
        schema = self._schemas[catalog_id]
        return deepcopy(schema)

    @property
    def catalog_ids(self) -> frozenset[str]:
        return frozenset(self._validators)


CATALOG_REGISTRY = CatalogRegistry()
CATALOG_REGISTRY.register_basic()
CATALOG_REGISTRY.register_packaged(
    catalog_id=A2UI_FINANCE_CATALOG,
    package="supabase_mcp.a2ui_support.catalogs",
    resource_name="finance_v1.json",
    name="fluidbank-finance-v1",
)
CATALOG_REGISTRY.register_finance_v2()
