"""Authenticate fixed write requests from the trusted orchestrator over remote MCP."""

import hashlib
import hmac
import json
from typing import Any

from pydantic import SecretStr

from supabase_mcp.a2ui_support.actions import ActionDispatchError


def verify_action_proof(
    secret: SecretStr | None, proof: str | None, payload: dict[str, Any]
) -> None:
    if secret is None or len(secret.get_secret_value()) < 32:
        raise ActionDispatchError(
            "writes_not_configured", "El servicio todavía no tiene habilitado el guardado."
        )
    if not isinstance(proof, str) or len(proof) != 64:
        raise ActionDispatchError(
            "untrusted_action", "No se pudo verificar la autorización de la acción."
        )
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    expected = hmac.new(secret.get_secret_value().encode(), encoded, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, proof):
        raise ActionDispatchError(
            "untrusted_action", "No se pudo verificar la autorización de la acción."
        )
