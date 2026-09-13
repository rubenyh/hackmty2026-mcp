"""User-confirmed financial forms; all writes go through DatabaseClient."""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastmcp import Context
from fastmcp.tools import ToolResult
from mcp.types import TextContent
from pydantic import BaseModel, Field

from supabase_mcp.a2ui_actions.registry import ACTIONS, CONTEXTS
from supabase_mcp.a2ui_support.actions import A2UIActionCall, ActionDispatchError, RegisteredAction
from supabase_mcp.a2ui_support.response import A2UIResponseFactory
from supabase_mcp.a2ui_support.surfaces import ACTION_SURFACES
from supabase_mcp.database import DatabaseClient
from supabase_mcp.errors import InvalidSelectionError
from supabase_mcp.models import SelectRequest, UserScope
from supabase_mcp.tools.health import _database


async def _owned_rows(
    database: DatabaseClient,
    scope: UserScope,
    table: str,
    columns: list[str],
) -> list[dict[str, Any]]:
    rows, _, _ = await database.select_rows(
        SelectRequest(
            schema="public",
            table=table,
            scope=scope,
            columns=columns,
            limit=50,
        )
    )
    return rows


async def _accounts_with_details(
    database: DatabaseClient, scope: UserScope
) -> list[dict[str, Any]]:
    accounts = await _owned_rows(
        database,
        scope,
        "accounts",
        ["id", "account_type", "currency", "available_balance"],
    )
    details = await _owned_rows(
        database,
        scope,
        "account_details",
        ["account_id", "display_name", "last_four"],
    )
    detail_by_account = {str(row["account_id"]): row for row in details}
    return [
        {**row, **detail_by_account[str(row["id"])]}
        for row in accounts
        if str(row["id"]) in detail_by_account
    ]


def _account_label(row: dict[str, Any]) -> str:
    ending = f" · •••• {row['last_four']}" if row.get("last_four") else ""
    return f"{row['display_name']}{ending}"


async def _prepare_transfer(
    database: DatabaseClient, scope: UserScope, form: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    accounts = await _accounts_with_details(database, scope)
    sources = [
        row
        for row in accounts
        if row["currency"] == "MXN"
        and row["account_type"] in {"checking", "savings"}
        and float(row["available_balance"]) > 0
    ]
    sources.sort(
        key=lambda row: (row["account_type"] != "checking", -float(row["available_balance"]))
    )
    beneficiaries = await _owned_rows(
        database,
        scope,
        "beneficiaries",
        ["display_name", "bank_name", "last_four", "status"],
    )
    beneficiaries = [row for row in beneficiaries if row["status"] != "inactive"]
    own_destinations = [
        row
        for row in accounts
        if row["currency"] == "MXN" and row["account_type"] in {"checking", "savings"}
    ]
    if sources:
        form["source_account"] = str(sources[0]["display_name"])
        form["amount"] = min(500, float(sources[0]["available_balance"]))
    if beneficiaries:
        form["recipient"] = str(beneficiaries[0]["display_name"])
    elif sources:
        target = next(
            (row for row in own_destinations if row["id"] != sources[0]["id"]),
            None,
        )
        if target:
            form["recipient"] = str(target["display_name"])
    source_text = ", ".join(
        f"{_account_label(row)} ({float(row['available_balance']):,.2f} MXN)" for row in sources
    )
    recipient_text = ", ".join(
        f"{row['display_name']} · {row['bank_name']} · •••• {row['last_four']}"
        for row in beneficiaries
    )
    own_account_text = ", ".join(_account_label(row) for row in own_destinations)
    if not sources or (not beneficiaries and len(own_destinations) < 2):
        return (
            "Necesitas una cuenta con saldo y otro destino disponible para transferir.",
            {},
        )
    return (
        f"Elige por nombre exacto. Cuentas de origen: {source_text}. "
        f"Cuentas propias: {own_account_text}. Destinatarios: {recipient_text or 'ninguno'}. "
        "El botón confirma el movimiento inmediato en MXN y no cobra comisión.",
        {},
    )


async def _prepare_credit_card_payment(
    database: DatabaseClient, scope: UserScope, form: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    accounts = await _accounts_with_details(database, scope)
    accounts_by_id = {str(row["id"]): row for row in accounts}
    sources = [
        row
        for row in accounts
        if row["currency"] == "MXN"
        and row["account_type"] in {"checking", "savings"}
        and float(row["available_balance"]) > 0
    ]
    sources.sort(
        key=lambda row: (row["account_type"] != "checking", -float(row["available_balance"]))
    )
    cards = await _owned_rows(
        database,
        scope,
        "cards",
        [
            "id",
            "account_id",
            "display_name",
            "card_type",
            "network",
            "last_four",
            "status",
            "expires_month",
            "expires_year",
        ],
    )
    terms = await _owned_rows(
        database,
        scope,
        "credit_card_terms",
        [
            "account_id",
            "currency",
            "credit_limit",
            "current_debt",
            "statement_balance",
            "minimum_payment",
            "interest_free_payment",
            "annual_interest_rate",
            "cat_percentage",
            "cutoff_date",
            "due_date",
        ],
    )
    terms_by_account = {str(row["account_id"]): row for row in terms}
    eligible_cards = [
        row
        for row in cards
        if row["card_type"] == "credit"
        and row["status"] == "active"
        and str(row["account_id"]) in accounts_by_id
        and str(row["account_id"]) in terms_by_account
        and terms_by_account[str(row["account_id"])]["currency"] == "MXN"
    ]
    if not sources or not eligible_cards:
        empty_preview: dict[str, Any] = {
            "intent": "credit-card",
            "state": "empty",
            "title": "Pagar tarjeta de crédito",
            "currency": "MXN",
            "description": (
                "No hay una tarjeta de crédito activa y una cuenta con saldo "
                "para completar el pago."
            ),
        }
        return (
            "Necesitas una tarjeta de crédito activa y una cuenta en MXN con saldo disponible.",
            {"preview": empty_preview},
        )
    source = sources[0]
    card = eligible_cards[0]
    account = accounts_by_id[str(card["account_id"])]
    term = terms_by_account[str(card["account_id"])]
    debt = float(term["current_debt"])
    suggested = min(
        float(term["interest_free_payment"]),
        float(source["available_balance"]),
        debt,
        100_000,
    )
    form.update(
        {
            "source_account": str(source["display_name"]),
            "card": str(card["display_name"]),
            "amount": max(1, suggested),
        }
    )
    card_data: dict[str, Any] = {
        "cardId": str(card["id"]),
        "cardName": str(card["display_name"]),
        "cardType": "credit",
        "network": card["network"],
        "lastFour": card["last_four"],
        "status": card["status"],
        "accountId": str(card["account_id"]),
    }
    if card.get("expires_year") and card.get("expires_month"):
        card_data["expires"] = f"{int(card['expires_year']):04d}-{int(card['expires_month']):02d}"
    preview: dict[str, Any] = {
        "intent": "credit-card",
        "title": "Tu tarjeta de crédito",
        "subtitle": "Revisa sus condiciones antes de confirmar el pago.",
        "currency": "MXN",
        "cardName": card["display_name"],
        "lastFour": card["last_four"],
        "debt": debt,
        "availableCredit": float(account["available_balance"]),
        "minimumPayment": float(term["minimum_payment"]),
        "interestFreePayment": float(term["interest_free_payment"]),
        "dueDate": str(term["due_date"]),
        "card": card_data,
        "creditLimit": float(term["credit_limit"]),
        "statementBalance": float(term["statement_balance"]),
        "cutoffDate": str(term["cutoff_date"]),
        "annualInterestRate": float(term["annual_interest_rate"]),
    }
    if term.get("cat_percentage") is not None:
        preview["catPercentage"] = float(term["cat_percentage"])
    source_text = ", ".join(
        f"{_account_label(row)} ({float(row['available_balance']):,.2f} MXN)" for row in sources
    )
    card_text = ", ".join(
        f"{row['display_name']} · •••• {row['last_four']}" for row in eligible_cards
    )
    return (
        f"Elige por nombre exacto. Cuentas para pagar: {source_text}. Tarjetas: {card_text}. "
        "El importe no puede superar el saldo disponible ni la deuda actual.",
        {"preview": preview},
    )


def action_outcome(success: bool, message: str, code: str | None = None) -> ToolResult:
    result = {"status": "success" if success else "failure", "message": message}
    if code:
        result["code"] = code
    return ToolResult(
        content=[TextContent(text=message)],
        structured_content={"ok": success, "actionResult": result},
        is_error=not success,
    )


async def prepare_form(
    name: str, database: DatabaseClient, scope: UserScope, values: dict[str, Any] | None = None
) -> ToolResult:
    spec = ACTIONS[name]
    form = {field["key"]: field["default"] for field in spec["inputs"]}
    today = datetime.now(ZoneInfo("America/Monterrey")).date()
    form.update(
        {
            key: today.isoformat()
            if key == "start_date"
            else (today + timedelta(days=30)).isoformat()
            for key in form
            if key.endswith("_date")
        }
    )
    help_text = (
        "Revisa los datos. Al pulsar el botón se guardarán en tu cuenta. "
        "Importes en MXN; esta acción no mueve dinero."
    )
    extra_data: dict[str, Any] = {}
    if name == "transfer.execute":
        help_text, extra_data = await _prepare_transfer(database, scope, form)
    elif name == "credit_card.pay":
        help_text, extra_data = await _prepare_credit_card_payment(database, scope, form)
    if name.endswith(".load"):
        table = "budgets" if name.startswith("budget.") else "savings_goals"
        rows, _, truncated = await database.select_rows(
            SelectRequest(
                schema="public",
                table=table,
                scope=scope,
                columns=["id", "name", "currency"],
                limit=50,
            )
        )
        names = [str(row["name"]) for row in rows if row["currency"] == "MXN"]
        help_text = (
            "Escribe el nombre de uno de tus registros: " + ", ".join(names)
            if names
            else "No tienes registros en MXN para editar. Puedes crear uno nuevo."
        )
        if truncated:
            help_text += " Se muestran los primeros 50 registros."
    if values:
        form.update({key: values[key] for key in spec["contextFields"] if key in values})
    return A2UIResponseFactory(ACTION_SURFACES[name]).build(
        fallback_text=spec["title"],
        data_model={"form": form, "help": help_text, **extra_data},
    )


async def a2ui_form(
    name: Literal[
        "budget.create",
        "budget.load",
        "savings_goal.create",
        "savings_goal.load",
        "transfer.execute",
        "credit_card.pay",
    ],
    ctx: Context,
    trustedScope: UserScope,
    initial_amount: Annotated[float, Field(gt=0, le=100_000)] | None = None,
    initial_recipient: Annotated[str, Field(min_length=1, max_length=120)] | None = None,
) -> ToolResult:
    """Prepare a form. This tool never saves changes; only a user Button event can save."""
    try:
        if initial_recipient is not None and name != "transfer.execute":
            return action_outcome(
                False,
                "La sugerencia inicial no corresponde a este formulario.",
                "invalid_prefill",
            )
        values: dict[str, Any] = {}
        if initial_amount is not None:
            values["amount"] = initial_amount
        if initial_recipient is not None:
            values["recipient"] = initial_recipient.strip()
        return await prepare_form(name, _database(ctx), trustedScope, values)
    except Exception:
        return action_outcome(
            False, "No se pudo cargar el formulario. Inténtalo de nuevo.", "form_unavailable"
        )


async def handle_form_action(
    call: A2UIActionCall, context: BaseModel, scope: UserScope | None, database: DatabaseClient
) -> ToolResult:
    if scope is None:
        raise ActionDispatchError("missing_trusted_scope", "Inicia sesión para guardar cambios.")
    values = context.model_dump(mode="json")
    try:
        if call.name.endswith(".load"):
            table = "budgets" if call.name.startswith("budget.") else "savings_goals"
            target = call.name.replace(".load", ".update")
            from supabase_mcp.models import FilterCondition, FilterOperator

            rows, _, _ = await database.select_rows(
                SelectRequest(
                    schema="public",
                    table=table,
                    scope=scope,
                    columns=["currency", *ACTIONS[target]["contextFields"]],
                    filters=[
                        FilterCondition(
                            column="name", operator=FilterOperator.EQ, value=values["name"]
                        )
                    ],
                    limit=2,
                )
            )
            if len(rows) != 1 or rows[0]["currency"] != "MXN":
                return action_outcome(
                    False,
                    "No se encontró un único registro en MXN con ese nombre. "
                    "Revisa el nombre exacto.",
                    "record_not_available",
                )
            return await prepare_form(target, database, scope, rows[0])
        request_key = hashlib.sha256(
            f"{call.surface_id}:{call.source_component_id}:{call.timestamp.isoformat()}".encode()
        ).hexdigest()
        payload_hash = hashlib.sha256(
            json.dumps(
                {"name": call.name, "context": values}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        result = await database.apply_financial_action(
            call.name, values, scope, request_key, payload_hash
        )
        if call.name == "transfer.execute":
            return action_outcome(
                True,
                f"Transferencia completada por {float(result['amount']):,.2f} MXN.",
            )
        if call.name == "credit_card.pay":
            return action_outcome(
                True,
                f"Pago aplicado a tu tarjeta por {float(result['amount']):,.2f} MXN.",
            )
        return action_outcome(True, "Cambios guardados correctamente en tu cuenta.")
    except InvalidSelectionError as exc:
        return action_outcome(False, exc.safe_message, exc.code)
    except Exception:
        return action_outcome(
            False,
            "No se pudo confirmar el guardado. Revisa la conexión "
            "y vuelve a intentar la misma operación.",
            "save_not_confirmed",
        )


def register_form_actions(registry: Any) -> None:
    for name, spec in ACTIONS.items():
        registry.register(
            RegisteredAction(
                name=name,
                surface_id=spec["surfaceId"],
                source_component_id=spec["sourceComponentId"],
                context_model=CONTEXTS[name],
                handler=handle_form_action,
                requires_trusted_scope=True,
            )
        )
