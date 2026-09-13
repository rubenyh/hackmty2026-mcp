"""Shared execution, validation, and observability boundary for financial tools."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter
from typing import Any, TypeVar
from uuid import uuid4

from fastmcp import Context
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import TextContent
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import (
    DBAPIError,
    DisconnectionError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from supabase_mcp.errors import PublicErrorCode, SafeMCPError
from supabase_mcp.serialization import to_json_safe
from supabase_mcp.tools.health import _database

logger = logging.getLogger(__name__)
RequestT = TypeVar("RequestT", bound=BaseModel)

_SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_PERMISSION_SQLSTATES = frozenset({"28000", "28P01", "42501"})
_TIMEOUT_SQLSTATES = frozenset({"57014"})
_SAFE_ERROR_CODES: dict[str, PublicErrorCode] = {
    "invalid_cursor": PublicErrorCode.INVALID_CURSOR,
    "invalid_period": PublicErrorCode.INVALID_DATE_RANGE,
    "unknown_user_id": PublicErrorCode.USER_SCOPE_ERROR,
    "user_scope_not_configured": PublicErrorCode.DATABASE_PERMISSION_ERROR,
    "object_not_allowed": PublicErrorCode.DATABASE_PERMISSION_ERROR,
    "column_not_allowed": PublicErrorCode.DATABASE_QUERY_ERROR,
    "ownership_filter_not_allowed": PublicErrorCode.VALIDATION_ERROR,
    "resource_not_found": PublicErrorCode.NOT_FOUND,
    "invalid_data": PublicErrorCode.DATA_MAPPING_ERROR,
}
_ERROR_DEFINITIONS: dict[PublicErrorCode, tuple[str, bool, str, str]] = {
    PublicErrorCode.VALIDATION_ERROR: (
        "Los argumentos de la consulta financiera no son válidos.",
        False,
        "request_validation",
        "Corrige los parámetros indicados y vuelve a intentar.",
    ),
    PublicErrorCode.INVALID_DATE_RANGE: (
        "El rango de fechas de la consulta financiera no es válido.",
        False,
        "request_validation",
        "Usa ambas fechas y asegúrate de que la fecha final no sea anterior a la inicial.",
    ),
    PublicErrorCode.INVALID_CURSOR: (
        "El cursor de paginación no es válido.",
        False,
        "request_validation",
        "Omite el cursor o usa el next_cursor devuelto por la consulta anterior.",
    ),
    PublicErrorCode.USER_SCOPE_ERROR: (
        "No se pudo validar el ámbito del usuario autenticado.",
        False,
        "user_scope",
        "Verifica la sesión autenticada y conserva su current_user_id.",
    ),
    PublicErrorCode.NOT_FOUND: (
        "No se encontró el recurso financiero solicitado dentro del ámbito del usuario.",
        False,
        "domain_service",
        "Verifica el identificador del recurso.",
    ),
    PublicErrorCode.DATABASE_UNAVAILABLE: (
        "La base de datos financiera no está disponible.",
        True,
        "database",
        "Intenta nuevamente; si persiste, verifica conectividad y configuración.",
    ),
    PublicErrorCode.DATABASE_TIMEOUT: (
        "La consulta financiera excedió el tiempo permitido.",
        True,
        "database",
        "Reduce el rango o los filtros y vuelve a intentar.",
    ),
    PublicErrorCode.DATABASE_PERMISSION_ERROR: (
        "La base de datos rechazó la consulta financiera por permisos.",
        False,
        "database",
        "Verifica la allowlist y los permisos SELECT del rol de lectura.",
    ),
    PublicErrorCode.DATABASE_QUERY_ERROR: (
        "La base de datos no pudo completar la consulta financiera.",
        False,
        "database",
        "Verifica el esquema esperado o ajusta los parámetros de la consulta.",
    ),
    PublicErrorCode.DATA_MAPPING_ERROR: (
        "Los datos financieros recibidos no tienen el formato esperado.",
        False,
        "data_mapping",
        "Verifica la forma y los tipos de las columnas consultadas.",
    ),
    PublicErrorCode.INTERNAL_ERROR: (
        "Ocurrió un error interno al procesar la consulta financiera.",
        False,
        "tool",
        "Reporta el correlation_id para investigar el fallo.",
    ),
}


def _bounded_correlation_id(value: object) -> str | None:
    text = str(value) if value is not None else ""
    return text if _SAFE_CORRELATION_ID.fullmatch(text) else None


def _correlation_id(ctx: Context | None) -> str:
    """Reuse safe MCP request metadata/ID, otherwise create an opaque ID."""
    if ctx is not None:
        try:
            request_context = ctx.request_context
            meta = request_context.meta if request_context is not None else None
            if isinstance(meta, Mapping):
                for key in ("correlation_id", "correlationId"):
                    candidate = _bounded_correlation_id(meta.get(key))
                    if candidate is not None:
                        return candidate
        except (AttributeError, RuntimeError):
            pass
        try:
            candidate = _bounded_correlation_id(ctx.origin_request_id)
            if candidate is not None:
                return candidate
        except (AttributeError, RuntimeError):
            pass
    return str(uuid4())


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending and len(chain) < 8:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        chain.append(current)
        for related in (
            current.__cause__,
            current.__context__,
            getattr(current, "orig", None),
        ):
            if isinstance(related, BaseException):
                pending.append(related)
    return chain


def _sqlstate(exc: BaseException) -> str | None:
    for candidate in _exception_chain(exc):
        for name in ("sqlstate", "pgcode"):
            try:
                value = getattr(candidate, name, None)
            except Exception:
                value = None
            if isinstance(value, str):
                return value
        try:
            value = getattr(getattr(candidate, "diag", None), "sqlstate", None)
        except Exception:
            value = None
        if isinstance(value, str):
            return value
    return None


def _classify_error(exc: BaseException) -> PublicErrorCode:
    """Classify without inspecting or returning exception messages."""
    if isinstance(exc, SafeMCPError):
        if exc.code in PublicErrorCode._value2member_map_:
            return PublicErrorCode(exc.code)
        return _SAFE_ERROR_CODES.get(exc.code, PublicErrorCode.VALIDATION_ERROR)
    if isinstance(exc, PydanticValidationError):
        if any(item.get("type") == "invalid_date_range" for item in exc.errors()):
            return PublicErrorCode.INVALID_DATE_RANGE
        return PublicErrorCode.VALIDATION_ERROR

    state = _sqlstate(exc)
    if state in _TIMEOUT_SQLSTATES:
        return PublicErrorCode.DATABASE_TIMEOUT
    if state in _PERMISSION_SQLSTATES:
        return PublicErrorCode.DATABASE_PERMISSION_ERROR
    if state is not None and state.startswith("08"):
        return PublicErrorCode.DATABASE_UNAVAILABLE

    chain = _exception_chain(exc)
    if any(isinstance(item, (TimeoutError, SQLAlchemyTimeoutError)) for item in chain):
        return PublicErrorCode.DATABASE_TIMEOUT
    if any(
        isinstance(item, (ConnectionError, OSError, DisconnectionError, InterfaceError))
        for item in chain
    ):
        return PublicErrorCode.DATABASE_UNAVAILABLE
    if any(isinstance(item, OperationalError) for item in chain):
        return PublicErrorCode.DATABASE_UNAVAILABLE
    if any(isinstance(item, (DBAPIError, SQLAlchemyError)) for item in chain):
        return PublicErrorCode.DATABASE_QUERY_ERROR
    if isinstance(exc, (KeyError, IndexError, TypeError)):
        return PublicErrorCode.DATA_MAPPING_ERROR
    return PublicErrorCode.INTERNAL_ERROR


def _error_result(
    code: PublicErrorCode,
    *,
    tool: str,
    operation: str,
    correlation_id: str,
) -> ToolResult:
    message, retryable, layer, suggestion = _ERROR_DEFINITIONS[code]
    payload = {
        "ok": False,
        "error": {
            "code": code.value,
            "message": message,
            "tool": tool,
            "retryable": retryable,
            "details": {
                "layer": layer,
                "operation": operation,
                "suggestion": suggestion,
            },
            "correlation_id": correlation_id,
        },
    }
    return ToolResult(
        content=[TextContent(text=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))],
        structured_content=payload,
        is_error=True,
    )


def _redacted_exc_info(exc: BaseException) -> tuple[type[BaseException], BaseException, Any]:
    """Keep traceback frames while replacing possibly sensitive exception text."""
    redacted = RuntimeError(f"{type(exc).__name__}: details redacted")
    return type(redacted), redacted, exc.__traceback__


def _log_failure(
    *,
    tool: str,
    operation: str,
    correlation_id: str,
    code: PublicErrorCode,
    started_at: float,
    exc: BaseException,
) -> None:
    duration_ms = round((perf_counter() - started_at) * 1000, 3)
    source_code = exc.code if isinstance(exc, SafeMCPError) else None
    database_sqlstate = _sqlstate(exc)
    logger.error(
        "financial_tool_failed tool=%s operation=%s correlation_id=%s code=%s "
        "duration_ms=%s exception_type=%s source_code=%s sqlstate=%s",
        tool,
        operation,
        correlation_id,
        code.value,
        duration_ms,
        type(exc).__name__,
        source_code,
        database_sqlstate,
        extra={
            "tool_name": tool,
            "operation": operation,
            "correlation_id": correlation_id,
            "error_code": code.value,
            "duration_ms": duration_ms,
            "exception_type": type(exc).__name__,
            "source_code": source_code,
            "sqlstate": database_sqlstate,
        },
        exc_info=_redacted_exc_info(exc),
    )


def _failure_result(
    exc: Exception,
    *,
    tool: str,
    operation: str,
    correlation_id: str,
    started_at: float,
) -> ToolResult:
    code = _classify_error(exc)
    _log_failure(
        tool=tool,
        operation=operation,
        correlation_id=correlation_id,
        code=code,
        started_at=started_at,
        exc=exc,
    )
    return _error_result(
        code,
        tool=tool,
        operation=operation,
        correlation_id=correlation_id,
    )


def _row_count(data: Mapping[str, Any]) -> int | None:
    for key in ("count", "row_count"):
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    for key in (
        "accounts",
        "transactions",
        "series",
        "budgets",
        "goals",
        "debts",
        "items",
        "alerts",
        "statements",
        "beneficiaries",
        "disputes",
        "scenarios",
    ):
        value = data.get(key)
        if isinstance(value, list):
            return len(value)
    return None


async def _run(
    tool: str,
    request: RequestT,
    ctx: Context,
    handler: Callable[[Any, RequestT], Awaitable[dict[str, Any]]],
) -> ToolResult:
    operation = handler.__name__
    correlation_id = _correlation_id(ctx)
    started_at = perf_counter()
    logger.info(
        "financial_tool_started tool=%s operation=%s correlation_id=%s",
        tool,
        operation,
        correlation_id,
        extra={
            "tool_name": tool,
            "operation": operation,
            "correlation_id": correlation_id,
        },
    )
    try:
        raw_data = await handler(_database(ctx), request)
        if not isinstance(raw_data, Mapping):
            raise SafeMCPError("invalid_data", "Financial result shape is invalid.")
        data = to_json_safe(raw_data)
        duration_ms = round((perf_counter() - started_at) * 1000, 3)
        row_count = _row_count(raw_data)
        logger.info(
            "financial_tool_completed tool=%s operation=%s correlation_id=%s "
            "duration_ms=%s row_count=%s",
            tool,
            operation,
            correlation_id,
            duration_ms,
            row_count,
            extra={
                "tool_name": tool,
                "operation": operation,
                "correlation_id": correlation_id,
                "duration_ms": duration_ms,
                "row_count": row_count,
            },
        )
        return ToolResult(
            content=[
                TextContent(text="Financial data retrieved. / Datos financieros consultados.")
            ],
            structured_content=data,
        )
    except (SafeMCPError, PydanticValidationError) as exc:
        return _failure_result(
            exc,
            tool=tool,
            operation=operation,
            correlation_id=correlation_id,
            started_at=started_at,
        )
    except (TimeoutError, SQLAlchemyError, ConnectionError, OSError) as exc:
        return _failure_result(
            exc,
            tool=tool,
            operation=operation,
            correlation_id=correlation_id,
            started_at=started_at,
        )
    except (KeyError, IndexError, TypeError) as exc:
        return _failure_result(
            exc,
            tool=tool,
            operation=operation,
            correlation_id=correlation_id,
            started_at=started_at,
        )
    except Exception as exc:
        return _failure_result(
            exc,
            tool=tool,
            operation=operation,
            correlation_id=correlation_id,
            started_at=started_at,
        )


class FinancialValidationMiddleware(Middleware):
    """Return structured, sanitized errors before FastMCP logs invalid arguments."""

    def __init__(self, request_models: Mapping[str, type[BaseModel]]) -> None:
        self._request_models = dict(request_models)

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, ToolResult],
    ) -> ToolResult:
        tool = context.message.name
        request_model = self._request_models.get(tool)
        if request_model is None:
            return await call_next(context)

        correlation_id = _correlation_id(context.fastmcp_context)
        started_at = perf_counter()
        arguments = context.message.arguments
        if not isinstance(arguments, Mapping) or set(arguments) != {"request"}:
            exc = ValueError("invalid financial tool envelope")
            code = PublicErrorCode.VALIDATION_ERROR
            _log_failure(
                tool=tool,
                operation="validate_request",
                correlation_id=correlation_id,
                code=code,
                started_at=started_at,
                exc=exc,
            )
            return _error_result(
                code,
                tool=tool,
                operation="validate_request",
                correlation_id=correlation_id,
            )
        try:
            request_model.model_validate(arguments["request"])
        except PydanticValidationError as exc:
            code = _classify_error(exc)
            _log_failure(
                tool=tool,
                operation="validate_request",
                correlation_id=correlation_id,
                code=code,
                started_at=started_at,
                exc=exc,
            )
            return _error_result(
                code,
                tool=tool,
                operation="validate_request",
                correlation_id=correlation_id,
            )
        return await call_next(context)


__all__ = ["FinancialValidationMiddleware", "_classify_error", "_run"]
