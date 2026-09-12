"""Explicit allowlisted dispatch for A2UI client actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastmcp.tools import ToolResult
from pydantic import BaseModel, Field, ValidationError, model_validator

from supabase_mcp.a2ui_support.surfaces import SurfaceRegistry
from supabase_mcp.database import DatabaseClient
from supabase_mcp.models import StrictModel
from supabase_mcp.services.database_overview import DATABASE_OVERVIEW_MAX_LIMIT

ActionHandler = Callable[[BaseModel, DatabaseClient], Awaitable[ToolResult]]


class ActionDispatchError(ValueError):
    """A client action could not be dispatched through the allowlist."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class A2UIActionCall(StrictModel):
    """The five protocol-defined fields received from an A2UI client."""

    name: str = Field(min_length=1, max_length=128)
    surface_id: str = Field(alias="surfaceId", min_length=1, max_length=128)
    source_component_id: str = Field(alias="sourceComponentId", min_length=1, max_length=128)
    timestamp: datetime
    context: dict[str, Any]

    @model_validator(mode="after")
    def require_timezone(self) -> A2UIActionCall:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return self


class RefreshDatabaseOverviewContext(StrictModel):
    """Validated context resolved from the refresh button's data bindings."""

    limit: int = Field(ge=1, le=DATABASE_OVERVIEW_MAX_LIMIT)


@dataclass(frozen=True, slots=True)
class RegisteredAction:
    name: str
    surface_id: str
    source_component_id: str
    context_model: type[BaseModel]
    handler: ActionHandler


class ActionRegistry:
    """Map fixed action names to validated handlers without dynamic dispatch."""

    def __init__(self, surfaces: SurfaceRegistry) -> None:
        self._surfaces = surfaces
        self._actions: dict[str, RegisteredAction] = {}

    def register(self, action: RegisteredAction) -> None:
        if action.name in self._actions:
            raise ValueError(f"Duplicate A2UI action name: {action.name}")
        surface = self._surfaces.get_by_id(action.surface_id)
        if surface is None:
            raise ValueError("A2UI action references an unregistered surface")
        if not self._template_declares_action(action):
            raise ValueError("A2UI action handler is not represented in its surface template")
        self._actions[action.name] = action

    async def dispatch(
        self,
        *,
        name: str,
        surface_id: str,
        source_component_id: str,
        timestamp: str,
        context: dict[str, Any],
        database: DatabaseClient,
    ) -> ToolResult:
        try:
            call = A2UIActionCall.model_validate(
                {
                    "name": name,
                    "surfaceId": surface_id,
                    "sourceComponentId": source_component_id,
                    "timestamp": timestamp,
                    "context": context,
                }
            )
        except ValidationError as exc:
            raise ActionDispatchError(
                "invalid_action", "The A2UI action envelope is invalid."
            ) from exc

        registered = self._actions.get(call.name)
        if registered is None:
            raise ActionDispatchError("unknown_action", "The A2UI action is not allowed.")
        if registered.surface_id != call.surface_id:
            raise ActionDispatchError(
                "surface_mismatch", "The A2UI action does not belong to this surface."
            )
        if registered.source_component_id != call.source_component_id:
            raise ActionDispatchError(
                "component_mismatch", "The A2UI action does not belong to this component."
            )
        try:
            validated_context = registered.context_model.model_validate(call.context)
        except ValidationError as exc:
            raise ActionDispatchError(
                "invalid_action_context", "The A2UI action context is invalid."
            ) from exc
        return await registered.handler(validated_context, database)

    def _template_declares_action(self, action: RegisteredAction) -> bool:
        surface = self._surfaces.get_by_id(action.surface_id)
        if surface is None:
            return False
        template = self._surfaces.template(surface)
        update = template[1].get("updateComponents")
        if not isinstance(update, dict):
            return False
        components = update.get("components")
        if not isinstance(components, list):
            return False
        for component in components:
            if not isinstance(component, dict) or component.get("id") != action.source_component_id:
                continue
            event = component.get("action", {}).get("event", {})
            return isinstance(event, dict) and event.get("name") == action.name
        return False
