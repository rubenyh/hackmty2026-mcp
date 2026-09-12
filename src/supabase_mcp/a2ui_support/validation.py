"""A2UI SDK-backed validation plus application-level surface invariants."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from supabase_mcp.a2ui_support.catalog_registry import CATALOG_REGISTRY, CatalogRegistry
from supabase_mcp.a2ui_support.constants import A2UI_VERSION
from supabase_mcp.a2ui_support.models import SurfaceSpec

_MESSAGE_KEYS = frozenset({"createSurface", "updateComponents", "updateDataModel", "deleteSurface"})


class A2UIValidationError(ValueError):
    """An A2UI payload failed a safe server-side invariant."""


class A2UIValidator:
    """Validate v0.9.1 messages with the official SDK and local integration rules."""

    def __init__(self, catalogs: CatalogRegistry | None = None) -> None:
        self._catalogs = catalogs or CATALOG_REGISTRY

    def validate_message(self, message: Mapping[str, Any], surface: SurfaceSpec) -> None:
        """Validate one dynamic message and ensure it targets the selected surface."""
        self._validate_envelope(message, surface)
        if "createSurface" in message:
            creation = message["createSurface"]
            if not isinstance(creation, Mapping) or creation.get("catalogId") != surface.catalog_id:
                raise A2UIValidationError("A2UI createSurface uses an unsupported catalog")
        self._sdk_validate(dict(message), surface.catalog_id)

    def validate_template(
        self, messages: Sequence[Mapping[str, Any]], surface: SurfaceSpec
    ) -> None:
        """Validate a static createSurface/updateComponents template as one stream."""
        if len(messages) != 2:
            raise A2UIValidationError(
                "An A2UI surface template must contain createSurface and updateComponents"
            )
        if "createSurface" not in messages[0] or "updateComponents" not in messages[1]:
            raise A2UIValidationError(
                "A2UI createSurface must precede the template updateComponents message"
            )

        for message in messages:
            self._validate_envelope(message, surface)

        creation = messages[0]["createSurface"]
        if not isinstance(creation, Mapping) or creation.get("catalogId") != surface.catalog_id:
            raise A2UIValidationError("A2UI template uses an unsupported catalog")

        update = messages[1]["updateComponents"]
        if not isinstance(update, Mapping):
            raise A2UIValidationError("A2UI updateComponents must be an object")
        components = update.get("components")
        if not isinstance(components, list):
            raise A2UIValidationError("A2UI template components must be a list")
        component_ids = [item.get("id") for item in components if isinstance(item, Mapping)]
        if len(component_ids) != len(components) or any(
            not isinstance(component_id, str) or not component_id for component_id in component_ids
        ):
            raise A2UIValidationError("Every A2UI component must have a non-empty string ID")
        if len(set(component_ids)) != len(component_ids):
            raise A2UIValidationError("A2UI component IDs must be unique within a surface")
        if "root" not in component_ids:
            raise A2UIValidationError("A2UI template must contain a root component")

        self._sdk_validate([dict(message) for message in messages], surface.catalog_id)

    @staticmethod
    def validate_json_pointer(path: str) -> None:
        """Accept an absolute JSON Pointer and reject malformed escape sequences."""
        if path == "/":
            return
        if not path.startswith("/") or "#" in path:
            raise A2UIValidationError("A2UI data model path must be an absolute JSON Pointer")
        index = 0
        while index < len(path):
            if path[index] == "~":
                if index + 1 >= len(path) or path[index + 1] not in {"0", "1"}:
                    raise A2UIValidationError("A2UI data model path has an invalid escape")
                index += 1
            index += 1

    @staticmethod
    def _validate_envelope(message: Mapping[str, Any], surface: SurfaceSpec) -> None:
        if message.get("version") != A2UI_VERSION:
            raise A2UIValidationError(f"A2UI messages must use {A2UI_VERSION}")
        message_keys = _MESSAGE_KEYS.intersection(message)
        if len(message_keys) != 1:
            raise A2UIValidationError("A2UI messages must contain exactly one message operation")
        body = message[next(iter(message_keys))]
        if not isinstance(body, Mapping) or body.get("surfaceId") != surface.surface_id:
            raise A2UIValidationError("A2UI message targets an unexpected surface")

    def _sdk_validate(
        self, payload: dict[str, Any] | list[dict[str, Any]], catalog_id: str
    ) -> None:
        try:
            self._catalogs.validator(catalog_id).validate(payload)
        except Exception as exc:
            raise A2UIValidationError(
                "A2UI payload does not conform to the official v0.9.1 schemas"
            ) from exc
