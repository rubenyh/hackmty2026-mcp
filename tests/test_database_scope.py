"""Query-level tests for mandatory application-owned demo-user scope."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

import pytest
from sqlalchemy import Boolean, Column, Date, DateTime, MetaData, Numeric, String, Table
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
        Column("occurred_at", DateTime(timezone=True), nullable=False),
        Column("posted_on", Date, nullable=True),
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


def _transactions_filter(value: object, *, column: str = "occurred_at", operator: str = "gte"):
    statement, _limit = _client().build_select(
        SelectRequest.model_validate(
            {
                "schema": "public",
                "table": "transactions",
                "scope": {"user_id": USER_A},
                "filters": [{"column": column, "operator": operator, "value": value}],
            }
        )
    )
    return statement.compile(dialect=postgresql.dialect())


def test_a_timestamp_filter_binds_a_datetime_rather_than_its_string() -> None:
    """A bound string never compared true, so every dated query returned nothing."""
    compiled = _transactions_filter("2026-08-14T00:00:37.023045+00:00")

    assert "public.transactions.occurred_at >=" in str(compiled)
    bound = [value for value in compiled.params.values() if isinstance(value, datetime)]
    assert bound == [datetime.fromisoformat("2026-08-14T00:00:37.023045+00:00")]
    assert not any(isinstance(value, str) for value in compiled.params.values())


def test_every_accepted_timestamp_spelling_reaches_the_same_instant() -> None:
    expected = datetime.fromisoformat("2026-08-14T00:00:00+00:00")
    for spelling in (
        "2026-08-14T00:00:00+00:00",
        "2026-08-14T00:00:00Z",
        "2026-08-14 00:00:00+00:00",
    ):
        compiled = _transactions_filter(spelling)
        assert expected in compiled.params.values(), spelling


def test_a_date_column_keeps_the_day_from_either_spelling() -> None:
    for spelling in ("2026-08-14", "2026-08-14T09:30:00+00:00"):
        compiled = _transactions_filter(spelling, column="posted_on")
        assert date(2026, 8, 14) in compiled.params.values(), spelling


def test_a_list_of_timestamps_is_converted_element_by_element() -> None:
    compiled = _transactions_filter(
        ["2026-08-14T00:00:00+00:00", "2026-08-15T00:00:00+00:00"],
        operator="in",
    )
    # An IN clause binds one expanding parameter holding the whole list.
    bound = [value for value in compiled.params.values() if isinstance(value, list)]
    assert bound == [
        [
            datetime.fromisoformat("2026-08-14T00:00:00+00:00"),
            datetime.fromisoformat("2026-08-15T00:00:00+00:00"),
        ]
    ]


def test_an_unparseable_temporal_filter_is_refused_instead_of_returning_nothing() -> None:
    """Silence was the real defect: a bad value must be an error, not zero rows."""
    for value in ("not-a-date", "2026-13-45T00:00:00+00:00", 1_760_000_000):
        with pytest.raises(InvalidSelectionError, match="ISO 8601"):
            _transactions_filter(value)


def test_non_temporal_filters_are_left_exactly_as_they_were() -> None:
    compiled = _transactions_filter("groceries", column="category", operator="eq")
    assert "groceries" in compiled.params.values()


def test_is_null_on_a_timestamp_column_still_takes_its_boolean() -> None:
    compiled = _transactions_filter(False, column="occurred_at", operator="is_null")
    assert "occurred_at IS NOT NULL" in str(compiled)
