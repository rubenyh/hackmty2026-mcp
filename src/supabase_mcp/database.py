"""Validated read access plus the fixed, separately configured action boundary."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from numbers import Number
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    MetaData,
    Select,
    Table,
    Time,
    asc,
    desc,
    exists,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
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
    UserScope,
)
from supabase_mcp.serialization import serialize_row

logger = logging.getLogger(__name__)

_ACTION_DATABASE_ERRORS = {
    "source_account_not_available": (
        "source_account_not_available",
        "No se encontró una única cuenta de origen disponible con ese nombre o terminación.",
    ),
    "recipient_not_available": (
        "recipient_not_available",
        "No se encontró un único destinatario disponible con ese nombre o terminación.",
    ),
    "external_recipient_not_supported": (
        "external_recipient_not_supported",
        "Ese contacto no está vinculado a una cuenta FluidBank y no puede recibir "
        "una transferencia local.",
    ),
    "recipient_matches_source": (
        "recipient_matches_source",
        "La cuenta de destino debe ser distinta de la cuenta de origen.",
    ),
    "recipient_account_not_available": (
        "recipient_account_not_available",
        "La cuenta vinculada al contacto ya no está disponible para recibir la transferencia.",
    ),
    "credit_card_not_available": (
        "credit_card_not_available",
        "No se encontró una única tarjeta de crédito activa con ese nombre o terminación.",
    ),
    "insufficient_funds": (
        "insufficient_funds",
        "La cuenta seleccionada no tiene saldo suficiente para completar la operación.",
    ),
    "payment_exceeds_debt": (
        "payment_exceeds_debt",
        "El pago no puede superar la deuda actual de la tarjeta.",
    ),
    "record_not_available": (
        "record_not_available",
        "El registro ya no está disponible. Actualiza la consulta e inténtalo de nuevo.",
    ),
    "idempotency_conflict": (
        "idempotency_conflict",
        "La confirmación ya fue usada con otros datos. Vuelve a abrir el formulario.",
    ),
}


@dataclass(frozen=True, slots=True)
class ReflectedObject:
    table: Table
    kind: str
    columns: tuple[ColumnDescription, ...]


@dataclass(frozen=True, slots=True)
class DirectScope:
    column: str


@dataclass(frozen=True, slots=True)
class JoinScope:
    local_column: str
    owner_schema: str
    owner_table: str
    owner_key: str
    owner_column: str


TableUserScope = DirectScope | JoinScope

# This map mirrors the checked-in schema history. Row-returning access to any
# other allowlisted object fails closed until an explicit ownership relationship is added.
TABLE_USER_SCOPES: dict[tuple[str, str], TableUserScope] = {
    ("public", "users"): DirectScope(column="id"),
    ("public", "accessibility_preferences"): DirectScope(column="user_id"),
    ("public", "accounts"): DirectScope(column="user_id"),
    ("public", "account_details"): DirectScope(column="user_id"),
    ("public", "cards"): DirectScope(column="user_id"),
    ("public", "credit_card_terms"): DirectScope(column="user_id"),
    ("public", "debts"): DirectScope(column="user_id"),
    ("public", "debt_scenarios"): DirectScope(column="user_id"),
    ("public", "budgets"): DirectScope(column="user_id"),
    ("public", "budget_progress"): DirectScope(column="user_id"),
    ("public", "savings_goals"): DirectScope(column="user_id"),
    ("public", "savings_goal_progress"): DirectScope(column="user_id"),
    ("public", "savings_contributions"): DirectScope(column="user_id"),
    ("public", "scheduled_cash_flows"): DirectScope(column="user_id"),
    ("public", "beneficiaries"): DirectScope(column="user_id"),
    ("public", "payment_orders"): DirectScope(column="user_id"),
    ("public", "transaction_disputes"): DirectScope(column="user_id"),
    ("public", "bank_statements"): DirectScope(column="user_id"),
    ("public", "financial_alerts"): DirectScope(column="user_id"),
    ("public", "transactions"): JoinScope(
        local_column="account_id",
        owner_schema="public",
        owner_table="accounts",
        owner_key="id",
        owner_column="user_id",
    ),
    ("public", "subscriptions"): DirectScope(column="user_id"),
    ("public", "transfers"): DirectScope(column="user_id"),
    ("public", "monthly_cash_flow"): JoinScope(
        local_column="account_id",
        owner_schema="public",
        owner_table="accounts",
        owner_key="id",
        owner_column="user_id",
    ),
}


_TEMPORAL_MESSAGE = "Filters on a date or time column require an ISO 8601 string value."
# Operators whose value is compared against the column. IS_NULL carries a
# boolean flag and LIKE/ILIKE carry patterns, so neither is a temporal value.
_COMPARISON_OPERATORS = frozenset(
    {
        FilterOperator.EQ,
        FilterOperator.NE,
        FilterOperator.GT,
        FilterOperator.GTE,
        FilterOperator.LT,
        FilterOperator.LTE,
        FilterOperator.IN,
    }
)


def _temporal_value(value: Any, column_type: Any) -> date | datetime | time | None:
    """Parse one JSON filter value into the object a temporal column compares against.

    Filter values arrive as JSON scalars, so a timestamp reaches us as a string.
    Binding that string against a DateTime column produced a predicate that was
    never true: every date-bounded query returned zero rows and no error, so
    balances kept working while spending, transactions and every dated chart
    came back silently empty.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str):
        raise InvalidSelectionError("invalid_filter_value", _TEMPORAL_MESSAGE)
    try:
        if isinstance(column_type, Time):
            return time.fromisoformat(value)
        if isinstance(column_type, Date):
            # A caller may send a full timestamp for a date column; keep the day.
            try:
                return date.fromisoformat(value)
            except ValueError:
                return datetime.fromisoformat(value).date()
        return datetime.fromisoformat(value)
    except ValueError:
        raise InvalidSelectionError("invalid_filter_value", _TEMPORAL_MESSAGE) from None


def _comparison_value(column: Any, condition: FilterCondition) -> Any:
    """Return the filter value with temporal strings converted, others untouched."""
    if condition.operator not in _COMPARISON_OPERATORS:
        return condition.value
    column_type = column.type
    if not isinstance(column_type, Date | DateTime | Time):
        return condition.value
    if isinstance(condition.value, list):
        return [_temporal_value(item, column_type) for item in condition.value]
    return _temporal_value(condition.value, column_type)


class DatabaseClient:
    """Own the shared engine and enforce the exact configured database surface."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._engine: AsyncEngine | None = None
        self._actions_engine: AsyncEngine | None = None
        self._objects: dict[tuple[str, str], ReflectedObject] = {}

    async def apply_financial_action(
        self,
        name: str,
        context: dict[str, Any],
        scope: UserScope,
        request_key: str,
        payload_hash: str,
    ) -> dict[str, Any]:
        """Only the authenticated UI dispatcher can enter this optional write boundary."""
        import json

        from sqlalchemy.engine import make_url

        if name not in {
            "budget.create",
            "budget.update",
            "savings_goal.create",
            "savings_goal.update",
            "transfer.execute",
            "credit_card.pay",
        }:
            raise InvalidSelectionError("unknown_action", "La acción no está permitida.")
        required_tables = {
            "budget.create": {"budgets"},
            "budget.update": {"budgets"},
            "savings_goal.create": {"savings_goals"},
            "savings_goal.update": {"savings_goals"},
            "transfer.execute": {
                "accounts",
                "account_details",
                "beneficiaries",
                "payment_orders",
                "transactions",
            },
            "credit_card.pay": {
                "accounts",
                "account_details",
                "cards",
                "credit_card_terms",
                "payment_orders",
                "transactions",
            },
        }[name]
        missing_tables = {
            table
            for table in required_tables
            if ("public", table) not in self.settings.allowed_table_pairs
        }
        if missing_tables:
            raise InvalidSelectionError(
                "table_not_allowed", "Falta habilitar información necesaria para esta acción."
            )
        configured = self.settings.actions_database_url
        if configured is None:
            raise InvalidSelectionError(
                "writes_not_configured",
                "El servicio todavía no tiene habilitado el guardado. No se realizó ningún cambio.",
            )
        if self._actions_engine is None:
            url = make_url(configured.get_secret_value()).set(drivername="postgresql+psycopg")
            if "sslmode" not in url.query:
                url = url.update_query_dict({"sslmode": "require"})
            self._actions_engine = create_async_engine(
                url, pool_size=2, max_overflow=0, pool_pre_ping=True
            )
        try:
            async with self._actions_engine.begin() as connection:
                role = (await connection.execute(text("select current_user"))).scalar_one()
                if role != "fluidbank_actions":
                    raise InvalidSelectionError(
                        "invalid_write_role", "La conexión de escritura no usa el rol permitido."
                    )
                await connection.execute(
                    text("select set_config('statement_timeout', :timeout, true)"),
                    {"timeout": str(self.settings.statement_timeout_ms)},
                )
                await connection.execute(
                    text("select set_config('request.jwt.claim.sub', :uid, true)"),
                    {"uid": str(scope.user_id)},
                )
                result = await connection.execute(
                    text(
                        "select public.apply_a2ui_action("
                        ":name, :key, :hash, cast(:context as jsonb))"
                    ),
                    {
                        "name": name,
                        "key": request_key,
                        "hash": payload_hash,
                        "context": json.dumps(context),
                    },
                )
                return dict(result.scalar_one())
        except DBAPIError as exc:
            database_message = str(exc.orig).lower()
            for marker, (code, safe_message) in _ACTION_DATABASE_ERRORS.items():
                if marker in database_message:
                    raise InvalidSelectionError(code, safe_message) from exc
            raise

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
        if self._actions_engine is not None:
            await self._actions_engine.dispose()
            self._actions_engine = None
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

    def build_select(self, request: SelectRequest) -> tuple[Select[Any], int]:
        """Validate a request and build a parameterized SQLAlchemy SELECT."""
        return self._build_select(request, allow_scope_column_filters=False)

    def _build_select(
        self, request: SelectRequest, *, allow_scope_column_filters: bool
    ) -> tuple[Select[Any], int]:
        """Build a select, optionally accepting service-validated ownership IDs."""
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

        control_columns = self.user_scope_columns(request.schema_name, request.table)
        if not allow_scope_column_filters and any(
            condition.column in control_columns for condition in request.filters
        ):
            raise InvalidSelectionError(
                "ownership_filter_not_allowed",
                "Ownership columns are controlled by the application user scope.",
            )

        statement = select(*selected_columns).where(
            self._user_scope_expression(
                request.schema_name,
                request.table,
                reflected,
                request.scope,
            )
        )
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

    def user_scope_columns(self, schema: str, table_name: str) -> frozenset[str]:
        """Return columns reserved for enforcing the configured ownership rule."""
        rule = TABLE_USER_SCOPES.get((schema, table_name))
        if rule is None:
            raise InvalidSelectionError(
                "user_scope_not_configured",
                "User-scoped access is not configured for the requested object.",
            )
        column = rule.column if isinstance(rule, DirectScope) else rule.local_column
        return frozenset({column})

    def _user_scope_expression(
        self,
        schema: str,
        table_name: str,
        reflected: ReflectedObject,
        scope: UserScope,
    ) -> Any:
        rule = TABLE_USER_SCOPES.get((schema, table_name))
        if rule is None:
            raise InvalidSelectionError(
                "user_scope_not_configured",
                "User-scoped access is not configured for the requested object.",
            )
        table = reflected.table
        if isinstance(rule, DirectScope):
            column = self._require_scope_column(table, rule.column)
            return column == scope.user_id

        local_column = self._require_scope_column(table, rule.local_column)
        owner = self._objects.get((rule.owner_schema, rule.owner_table))
        if owner is None:
            raise InvalidSelectionError(
                "user_scope_not_configured",
                "User-scoped access is not configured for the requested object.",
            )
        owner_key = self._require_scope_column(owner.table, rule.owner_key)
        owner_column = self._require_scope_column(owner.table, rule.owner_column)
        return exists(
            select(1)
            .select_from(owner.table)
            .where(owner_key == local_column, owner_column == scope.user_id)
        )

    @staticmethod
    def _require_scope_column(table: Table, name: str) -> Any:
        if name not in table.c:
            raise InvalidSelectionError(
                "user_scope_not_configured",
                "User-scoped access is not configured for the requested object.",
            )
        return table.c[name]

    @staticmethod
    def _filter_expression(column: Any, condition: FilterCondition) -> Any:
        operator = condition.operator
        if operator is FilterOperator.IS_NULL:
            return column.is_(None) if condition.value else column.is_not(None)
        value = _comparison_value(column, condition)
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
        raise InvalidSelectionError("operator_not_allowed", "The filter operator is not allowed.")

    async def select_scoped_rows(
        self, request: SelectRequest
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """Execute a validated selection in a bounded read-only transaction."""
        statement, limit = self.build_select(request)
        engine = self._require_engine()
        async with engine.connect() as connection:
            async with connection.begin():
                await self._configure_transaction(connection)
                await self._configure_user_scope(connection, request.scope)
                await self._validate_user_scope(connection, request.scope)
                result = await connection.execute(statement)
                mappings = result.mappings().all()
        truncated = len(mappings) > limit
        rows = [serialize_row(dict(row)) for row in mappings[:limit]]
        return rows, limit, truncated

    async def select_domain_rows(
        self, request: SelectRequest
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """Execute an internal domain read after its referenced IDs were ownership-checked.

        This is deliberately not exposed as an MCP tool. Domain services may add
        account filters that the stricter scoped helper rejects, while the
        canonical user-scope predicate remains mandatory in the same SQL statement.
        """
        statement, limit = self._build_select(request, allow_scope_column_filters=True)
        engine = self._require_engine()
        async with engine.connect() as connection:
            async with connection.begin():
                await self._configure_transaction(connection)
                await self._configure_user_scope(connection, request.scope)
                await self._validate_user_scope(connection, request.scope)
                result = await connection.execute(statement)
                mappings = result.mappings().all()
        truncated = len(mappings) > limit
        rows = [serialize_row(dict(row)) for row in mappings[:limit]]
        return rows, limit, truncated

    @staticmethod
    async def _configure_user_scope(connection: AsyncConnection, scope: UserScope) -> None:
        """Place the verified subject in the current transaction for RLS policies."""
        await connection.execute(
            text("select set_config('request.jwt.claim.sub', :uid, true)"),
            {"uid": str(scope.user_id)},
        )

    async def _validate_user_scope(self, connection: AsyncConnection, scope: UserScope) -> None:
        """Require the scoped id to be a real application user.

        Every signed-up account is mirrored into public.users, so existence in
        that table is the only membership test: the scope is rejected for an id
        nobody owns, and accepted for any real user.
        """
        users = self._objects.get(("public", "users"))
        if users is None or "id" not in users.table.c:
            raise InvalidSelectionError(
                "user_scope_not_configured",
                "User-scoped access is not configured for the requested object.",
            )
        known_user = await connection.scalar(
            select(exists().where(users.table.c.id == scope.user_id))
        )
        if known_user is not True:
            raise InvalidSelectionError(
                "unknown_user_id",
                "The selected user is not configured.",
            )
