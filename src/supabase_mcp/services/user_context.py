"""Fixed, ownership-scoped data needed to initialize one agent turn."""

from __future__ import annotations

import asyncio
from typing import Any

from supabase_mcp.database import DatabaseClient
from supabase_mcp.models import SelectRequest, UserScope


async def _read_context_table(
    database: DatabaseClient,
    scope: UserScope,
    table: str,
) -> list[dict[str, Any]]:
    rows, _limit, _truncated = await database.select_scoped_rows(
        SelectRequest(schema="public", table=table, scope=scope)
    )
    return rows


async def get_user_context_data(
    database: DatabaseClient,
    scope: UserScope,
) -> dict[str, Any]:
    """Read fixed context tables without exposing caller-selected database access."""
    users, preferences, accounts, subscriptions, cards = await asyncio.gather(
        _read_context_table(database, scope, "users"),
        _read_context_table(database, scope, "accessibility_preferences"),
        _read_context_table(database, scope, "accounts"),
        _read_context_table(database, scope, "subscriptions"),
        _read_context_table(database, scope, "cards"),
    )
    return {
        "ok": True,
        "user_found": bool(users),
        "preferences": preferences[0] if preferences else None,
        "accounts": accounts,
        "subscriptions": subscriptions,
        "cards": cards,
    }
