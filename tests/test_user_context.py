"""Fixed user-context service tests; no database connection is made."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from supabase_mcp.models import SelectRequest, UserScope
from supabase_mcp.services.user_context import get_user_context_data


class _Database:
    def __init__(self) -> None:
        self.requests: list[SelectRequest] = []

    async def select_scoped_rows(
        self, request: SelectRequest
    ) -> tuple[list[dict[str, Any]], int, bool]:
        self.requests.append(request)
        rows: dict[str, list[dict[str, Any]]] = {
            "users": [{"id": str(request.scope.user_id)}],
            "accessibility_preferences": [{"contrast": "high"}],
            "accounts": [{"id": "account-1"}],
            "subscriptions": [{"id": "subscription-1"}],
            "cards": [{"id": "card-1"}],
        }
        return rows[request.table], 50, False


async def test_user_context_owns_its_fixed_table_set() -> None:
    database = _Database()
    scope = UserScope(user_id=UUID("11111111-1111-1111-1111-111111111111"))

    result = await get_user_context_data(database, scope)  # type: ignore[arg-type]

    assert result == {
        "ok": True,
        "user_found": True,
        "preferences": {"contrast": "high"},
        "accounts": [{"id": "account-1"}],
        "subscriptions": [{"id": "subscription-1"}],
        "cards": [{"id": "card-1"}],
    }
    assert {request.table for request in database.requests} == {
        "users",
        "accessibility_preferences",
        "accounts",
        "subscriptions",
        "cards",
    }
    assert all(request.scope == scope for request in database.requests)
    assert all(request.filters == [] for request in database.requests)
