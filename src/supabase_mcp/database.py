"""Centralized, read-only SQLAlchemy access and query validation."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Number
from typing import Any

from sqlalchemy import MetaData, Select, Table, asc, desc, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from supabase_mcp.config import Settings
from supabase_mcp.errors import DatabaseConfigurationError, InvalidSelectionError
from supabase_mcp.models import (
    AllowedObject,
    ColumnDescription,
    FilterCondition,
    FilterOperator,
    OrderDirection,
    SelectRequest,
)
from supabase_mcp.serialization import serialize_row

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReflectedObject:
    table: Table
    kind: str
    columns: tuple[ColumnDescription, ...]


class DatabaseClient:
    """Own the shared engine and enforce the exact configured database surface."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._engine: AsyncEngine | None = None
        self._objects: dict[tuple[str, str], ReflectedObject] = {}

    async def start(self) -> None:
        """Create one engine and validate all configured allowlist entries."""
        if self._engine is not None:
            return
        self._engine = create_async_engine(
            self.settings.sqlalchemy_url(),
            pool_size=3,
            max_overflow=2,
            pool_timeout=5,
            pool_pre_ping=True,
        )
        try:
            if self.settings.allowed_table_pairs:
                async with self._engine.connect() as connection:
                    async with connection.begin():
                        await self._configure_transaction(connection)
                        reflected = await connection.run_sync(self._reflect_allowlist)
                self._objects = reflected
        except Exception as exc:
            logger.warning(
                "Database allowlist validation failed while starting DatabaseClient (%s)",
                type(exc).__name__,
            )
            await self.stop()
            raise DatabaseConfigurationError(
                "Could not validate MCP_ALLOWED_TABLES. Confirm object names, "
                "connectivity, TLS, and SELECT privileges for the dedicated "
                "database role."
            ) from exc

    async def stop(self) -> None:
        """Dispose the shared pool."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        self._objects = {}

    async def _configure_transaction(self, connection: AsyncConnection) -> None:
        await connection.execute(text("SET TRANSACTION READ ONLY"))
        await connection.execute(
            text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{self.settings.statement_timeout_ms}ms"},
        )

    def _reflect_allowlist(self, connection: Connection) -> dict[tuple[str, str], ReflectedObject]:
        inspector = inspect(connection)
        reflected: dict[tuple[str, str], ReflectedObject] = {}
        names_by_schema: dict[str, tuple[set[str], set[str]]] = {}

        for schema in self.settings.allowed_schemas:
            names_by_schema[schema] = (
                set(inspector.get_table_names(schema=schema)),
                set(inspector.get_view_names(schema=schema)),
            )

        for schema, table_name in self.settings.allowed_table_pairs:
            table_names, view_names = names_by_schema[schema]
            if table_name in table_names:
                kind = "table"
            elif table_name in view_names:
                kind = "view"
            else:
                raise DatabaseConfigurationError(
                    f"Allowlisted object {schema}.{table_name} does not exist as a table or view"
                )

            metadata = MetaData()
            table = Table(table_name, metadata, schema=schema, autoload_with=connection)
            primary_keys = {column.name for column in table.primary_key.columns}
            columns = tuple(
                ColumnDescription(
                    name=column.name,
                    data_type=str(column.type),
                    nullable=bool(column.nullable),
                    primary_key=column.name in primary_keys,
                )
                for column in table.columns
            )
            reflected[(schema, table_name)] = ReflectedObject(table, kind, columns)
        return reflected

    def _require_engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("database client is not started")
        return self._engine

    def _require_object(self, schema: str, table: str) -> ReflectedObject:
        reflected = self._objects.get((schema, table))
        if reflected is None:
            raise InvalidSelectionError(
                "object_not_allowed", "The requested schema and table are not allowlisted."
            )
        return reflected

    @staticmethod
    def _require_columns(table: Table, names: Sequence[str]) -> list[Any]:
        columns: list[Any] = []
        for name in names:
            if name not in table.c:
                raise InvalidSelectionError(
                    "column_not_allowed", f"Column '{name}' is not available on this object."
                )
            columns.append(table.c[name])
        return columns

    def list_allowed_objects(self) -> list[AllowedObject]:
        """Return the exact configured and reflected surface."""
        return [
            AllowedObject(schema=schema, table=table, kind=reflected.kind)
            for (schema, table), reflected in sorted(self._objects.items())
        ]

    def describe_table(self, schema: str, table: str) -> tuple[ColumnDescription, ...]:
        """Return cached safe metadata for an allowlisted table or view."""
        return self._require_object(schema, table).columns

    def require_numeric_columns(self, schema: str, table: str, names: Sequence[str]) -> None:
        """Reject requested value columns whose reflected SQL types are not numeric."""
        reflected = self._require_object(schema, table)
        columns = self._require_columns(reflected.table, names)
        for column in columns:
            try:
                python_type = column.type.python_type
            except (AttributeError, NotImplementedError) as exc:
                raise InvalidSelectionError(
                    "nonnumeric_column", f"Column '{column.name}' is not numeric."
                ) from exc
            try:
                numeric = python_type is not bool and issubclass(python_type, Number)
            except TypeError:
                numeric = False
            if not numeric:
                raise InvalidSelectionError(
                    "nonnumeric_column", f"Column '{column.name}' is not numeric."
                )

    async def health_check(self) -> None:
        """Run a minimal read-only database round trip."""
        engine = self._require_engine()
        async with engine.connect() as connection:
            async with connection.begin():
                await self._configure_transaction(connection)
                await connection.execute(text("SELECT 1"))

    def build_select(self, request: SelectRequest) -> tuple[Select[Any], int]:
        """Validate a request and build a parameterized SQLAlchemy SELECT."""
        reflected = self._require_object(request.schema_name, request.table)
        table = reflected.table
        limit = request.limit if request.limit is not None else self.settings.default_limit
        if limit > self.settings.max_limit:
            raise InvalidSelectionError(
                "limit_exceeded",
                f"limit must be between 1 and the configured maximum of {self.settings.max_limit}.",
            )

        if request.columns is None:
            selected_columns = list(table.c)
        else:
            if not request.columns:
                raise InvalidSelectionError(
                    "columns_required", "columns must be omitted or contain at least one column."
                )
            if len(set(request.columns)) != len(request.columns):
                raise InvalidSelectionError(
                    "duplicate_columns", "columns must not contain duplicates."
                )
            selected_columns = self._require_columns(table, request.columns)

        statement = select(*selected_columns)
        for condition in request.filters:
            column = self._require_columns(table, [condition.column])[0]
            statement = statement.where(self._filter_expression(column, condition))

        if request.order_by:
            for ordering in request.order_by:
                column = self._require_columns(table, [ordering.column])[0]
                statement = statement.order_by(
                    desc(column) if ordering.direction is OrderDirection.DESC else asc(column)
                )
        elif len(table.primary_key.columns) > 0:
            statement = statement.order_by(*(asc(column) for column in table.primary_key.columns))

        return statement.limit(limit + 1).offset(request.offset), limit

    @staticmethod
    def _filter_expression(column: Any, condition: FilterCondition) -> Any:
        operator = condition.operator
        value = condition.value
        if operator is FilterOperator.EQ:
            return column == value
        if operator is FilterOperator.NE:
            return column != value
        if operator is FilterOperator.GT:
            return column > value
        if operator is FilterOperator.GTE:
            return column >= value
        if operator is FilterOperator.LT:
            return column < value
        if operator is FilterOperator.LTE:
            return column <= value
        if operator is FilterOperator.IN:
            return column.in_(value)
        if operator is FilterOperator.LIKE:
            return column.like(value)
        if operator is FilterOperator.ILIKE:
            return column.ilike(value)
        if operator is FilterOperator.IS_NULL:
            return column.is_(None) if value else column.is_not(None)
        raise InvalidSelectionError("operator_not_allowed", "The filter operator is not allowed.")

    async def select_rows(self, request: SelectRequest) -> tuple[list[dict[str, Any]], int, bool]:
        """Execute a validated selection in a bounded read-only transaction."""
        statement, limit = self.build_select(request)
        engine = self._require_engine()
        async with engine.connect() as connection:
            async with connection.begin():
                await self._configure_transaction(connection)
                result = await connection.execute(statement)
                mappings = result.mappings().all()
        truncated = len(mappings) > limit
        rows = [serialize_row(dict(row)) for row in mappings[:limit]]
        return rows, limit, truncated
