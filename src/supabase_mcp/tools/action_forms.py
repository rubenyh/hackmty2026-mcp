"""User-confirmed budget/goal forms; all writes go through DatabaseClient."""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastmcp import Context
from fastmcp.tools import ToolResult
from mcp.types import TextContent
from pydantic import BaseModel

from supabase_mcp.a2ui_actions.registry import ACTIONS, CONTEXTS
from supabase_mcp.a2ui_support.actions import A2UIActionCall, ActionDispatchError, RegisteredAction
from supabase_mcp.a2ui_support.response import A2UIResponseFactory
from supabase_mcp.a2ui_support.surfaces import ACTION_SURFACES
from supabase_mcp.database import DatabaseClient
from supabase_mcp.errors import InvalidSelectionError
from supabase_mcp.models import SelectRequest, UserScope
from supabase_mcp.tools.health import _database


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
        fallback_text=spec["title"], data_model={"form": form, "help": help_text}
    )


async def a2ui_form(
    name: Literal["budget.create", "budget.load", "savings_goal.create", "savings_goal.load"],
    ctx: Context,
    trustedScope: UserScope,
) -> ToolResult:
    """Prepare a form. This tool never saves changes; only a user Button event can save."""
    try:
        return await prepare_form(name, _database(ctx), trustedScope)
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
        await database.apply_financial_action(call.name, values, scope, request_key, payload_hash)
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
