"""Allowlist, context, and error-reporting tests for A2UI client tools."""

from __future__ import annotations

import logging

import pytest
from pydantic import SecretStr

from supabase_mcp.a2ui_support.constants import (
    DATABASE_OVERVIEW_SURFACE_ID,
    REFRESH_DATABASE_OVERVIEW_ACTION,
    REFRESH_DATABASE_OVERVIEW_COMPONENT_ID,
)
from supabase_mcp.config import Settings
from supabase_mcp.database import DatabaseClient
from supabase_mcp.tools.a2ui import ACTION_REGISTRY, a2ui_error


def _database() -> DatabaseClient:
    return DatabaseClient(
        Settings(
            SUPABASE_DATABASE_URL=SecretStr(
                "postgresql://reader:password@localhost/postgres?sslmode=require"
            ),
            MCP_ALLOWED_TABLES="",
        )
    )


async def test_registered_refresh_action_returns_a2ui_result() -> None:
    result = await ACTION_REGISTRY.dispatch(
        name=REFRESH_DATABASE_OVERVIEW_ACTION,
        surface_id=DATABASE_OVERVIEW_SURFACE_ID,
        source_component_id=REFRESH_DATABASE_OVERVIEW_COMPONENT_ID,
        timestamp="2026-09-11T12:00:00Z",
        context={"limit": 10},
        database=_database(),
    )
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["ok"] is True


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"name": "not_registered"}, "unknown_action"),
        ({"surface_id": "another-surface"}, "surface_mismatch"),
        ({"source_component_id": "another-button"}, "component_mismatch"),
        ({"context": {"limit": 0}}, "invalid_action_context"),
    ],
)
async def test_action_registry_rejects_unsafe_dispatch(
    overrides: dict[str, object], code: str
) -> None:
    from supabase_mcp.a2ui_support.actions import ActionDispatchError

    arguments: dict[str, object] = {
        "name": REFRESH_DATABASE_OVERVIEW_ACTION,
        "surface_id": DATABASE_OVERVIEW_SURFACE_ID,
        "source_component_id": REFRESH_DATABASE_OVERVIEW_COMPONENT_ID,
        "timestamp": "2026-09-11T12:00:00Z",
        "context": {"limit": 10},
        "database": _database(),
    }
    arguments.update(overrides)
    with pytest.raises(ActionDispatchError) as captured:
        await ACTION_REGISTRY.dispatch(**arguments)  # type: ignore[arg-type]
    assert captured.value.code == code


async def test_a2ui_error_acknowledges_validation_without_leaking_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "database-password-should-not-appear"
    with caplog.at_level(logging.WARNING):
        result = await a2ui_error(
            code="VALIDATION_FAILED",
            surfaceId=DATABASE_OVERVIEW_SURFACE_ID,
            path="/components/0/text",
            message=secret,
        )
    assert result.structured_content == {
        "acknowledged": True,
        "validation_failed": True,
        "known_surface": True,
    }
    assert secret not in caplog.text
    assert secret not in result.content[0].text
