"""Query-level tests for mandatory application-owned demo-user scope."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import Boolean, Column, MetaData, Numeric, String, Table
from sqlalchemy.dialects import postgresql

from supabase_mcp.config import Settings
from supabase_mcp.database import (
    TABLE_USER_SCOPES,
    DatabaseClient,
    DirectScope,
    JoinScope,
    ReflectedObject,
)
from supabase_mcp.errors import InvalidSelectionError
from supabase_mcp.models import SelectRequest, UserScope

USER_A = "68dc4d66-07b8-5893-95f1-07f06989a552"


def test_ownership_registry_covers_every_seeded_data_object() -> None:
    assert TABLE_USER_SCOPES == {
        ("public", "users"): DirectScope("id"),
        ("public", "accessibility_preferences"): DirectScope("user_id"),
        ("public", "accounts"): DirectScope("user_id"),
        ("public", "transactions"): JoinScope("account_id", "public", "accounts", "id", "user_id"),
        ("public", "subscriptions"): DirectScope("user_id"),
        ("public", "transfers"): DirectScope("user_id"),
        ("public", "monthly_cash_flow"): JoinScope(
            "account_id", "public", "accounts", "id", "user_id"
        ),
    }


def _client() -> DatabaseClient:
    settings = Settings.model_validate(
        {
            "SUPABASE_DATABASE_URL": "postgresql://reader:placeholder@localhost/postgres",
            "MCP_ALLOWED_TABLES": (
                "public.users,public.accounts,public.transactions,public.subscriptions"
            ),
        }
    )
    client = DatabaseClient(settings)
    metadata = MetaData()
    users = Table(
        "users",
        metadata,
        Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        Column("is_demo", Boolean, nullable=False),
        schema="public",
    )
    accounts = Table(
        "accounts",
        metadata,
        Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        schema="public",
    )
    transactions = Table(
        "transactions",
        metadata,
        Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        Column("category", String, nullable=False),
        Column("amount", Numeric, nullable=False),
        schema="public",
    )
    subscriptions = Table(
        "subscriptions",
        metadata,
        Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        Column("status", String, nullable=False),
        schema="public",
    )
    client._objects = {
        ("public", table.name): ReflectedObject(table, "table", ())
        for table in (users, accounts, transactions, subscriptions)
    }
    return client


def test_indirect_scope_is_bound_and_anded_with_business_filters() -> None:
    statement, _limit = _client().build_select(
        SelectRequest.model_validate(
            {
                "schema": "public",
                "table": "transactions",
                "scope": {"user_id": USER_A},
                "filters": [{"column": "category", "operator": "eq", "value": "groceries"}],
            }
        )
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "EXISTS (SELECT 1" in sql
    assert "public.accounts.id = public.transactions.account_id" in sql
    assert "public.accounts.user_id =" in sql
    assert "public.transactions.category =" in sql
    assert " AND " in sql
    assert UUID(USER_A) in compiled.params.values()
    assert "groceries" in compiled.params.values()
    assert USER_A not in sql


def test_direct_scope_is_mandatory_and_ownership_filters_are_rejected() -> None:
    client = _client()
    statement, _limit = client.build_select(
        SelectRequest.model_validate(
            {
                "schema": "public",
                "table": "subscriptions",
                "scope": {"user_id": USER_A},
            }
        )
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "subscriptions.user_id =" in str(compiled)
    assert UUID(USER_A) in compiled.params.values()

    with pytest.raises(InvalidSelectionError, match="controlled by the application"):
        client.build_select(
            SelectRequest.model_validate(
                {
                    "schema": "public",
                    "table": "transactions",
                    "scope": {"user_id": USER_A},
                    "filters": [{"column": "account_id", "operator": "eq", "value": USER_A}],
                }
            )
        )


def test_unmapped_allowlisted_table_fails_closed() -> None:
    client = _client()
    mystery = Table("mystery", MetaData(), Column("value", Numeric), schema="public")
    client._objects[("public", "mystery")] = ReflectedObject(mystery, "table", ())

    with pytest.raises(InvalidSelectionError) as caught:
        client.build_select(
            SelectRequest.model_validate(
                {
                    "schema": "public",
                    "table": "mystery",
                    "scope": {"user_id": USER_A},
                }
            )
        )
    assert caught.value.code == "user_scope_not_configured"


@pytest.mark.asyncio
async def test_unknown_user_scope_fails_instead_of_returning_an_empty_success() -> None:
    class UnknownUserConnection:
        async def scalar(self, _statement: object) -> bool:
            return False

    with pytest.raises(InvalidSelectionError) as caught:
        await _client()._validate_user_scope(
            UnknownUserConnection(),  # type: ignore[arg-type]
            UserScope(user_id=USER_A),
        )
    assert caught.value.code == "unknown_user_id"


@pytest.mark.asyncio
async def test_any_real_user_is_accepted_without_a_demo_flag() -> None:
    """Scope membership is existence in public.users, not a demo marker."""
    captured: list[object] = []

    class KnownUserConnection:
        async def scalar(self, statement: object) -> bool:
            captured.append(statement)
            return True

    await _client()._validate_user_scope(
        KnownUserConnection(),  # type: ignore[arg-type]
        UserScope(user_id=USER_A),
    )
    assert "is_demo" not in str(captured[0])
