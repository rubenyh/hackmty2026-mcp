"""Offline coverage for form contracts, ownership, validation and write results."""

import pytest
from pydantic import SecretStr, ValidationError

from supabase_mcp.a2ui_actions.registry import ACTIONS, CONTEXTS
from supabase_mcp.a2ui_support.actions import ActionDispatchError
from supabase_mcp.config import Settings
from supabase_mcp.database import DatabaseClient
from supabase_mcp.models import UserScope
from supabase_mcp.tools.a2ui import ACTION_REGISTRY
from supabase_mcp.tools.action_forms import prepare_form

UID = "f52827d7-0213-4df4-9621-14775d6228d4"
VALUES = {
    "name": "Comida",
    "category": "groceries",
    "limit_amount": 3000,
    "start_date": "2026-09-13",
    "end_date": "2026-10-13",
}


class FakeDatabase:
    def __init__(self):
        self.calls = []

    async def apply_financial_action(self, *args):
        self.calls.append(args)
        return {"status": "success", "id": UID}


async def dispatch(db, **patch):
    args = dict(
        name="budget.create",
        surface_id="budget-create",
        source_component_id="submit",
        timestamp="2026-09-13T12:00:00Z",
        context=VALUES,
        database=db,
        trusted_scope={"user_id": UID},
    )
    args.update(patch)
    return await ACTION_REGISTRY.dispatch(**args)


async def test_confirmed_action_validates_and_uses_authenticated_scope():
    db = FakeDatabase()
    result = await dispatch(db)
    assert result.structured_content["actionResult"]["status"] == "success"
    assert str(db.calls[0][2].user_id) == UID
    await dispatch(db)
    assert db.calls[0][3:] == db.calls[1][3:]


@pytest.mark.parametrize(
    "patch",
    [
        {"trusted_scope": None},
        {"surface_id": "other"},
        {"source_component_id": "other"},
        {"context": {**VALUES, "user_id": UID}},
        {"context": {**VALUES, "limit_amount": -1}},
        {"context": {**VALUES, "end_date": "2026-02-30"}},
        {"context": {**VALUES, "end_date": "2026-01-01"}},
    ],
)
async def test_invalid_or_unowned_actions_never_write(patch):
    db = FakeDatabase()
    with pytest.raises(ActionDispatchError):
        await dispatch(db, **patch)
    assert db.calls == []


async def test_writes_disabled_returns_failure_not_simulated_success():
    db = DatabaseClient(
        Settings(
            _env_file=None,
            SUPABASE_DATABASE_URL=SecretStr("postgresql://reader:password@localhost/db"),
            MCP_ALLOWED_TABLES="public.budgets",
        )
    )
    result = await dispatch(db)
    assert result.is_error
    assert result.structured_content["actionResult"]["code"] == "writes_not_configured"


async def test_validation_identifies_the_field_without_echoing_its_value():
    with pytest.raises(ActionDispatchError) as error:
        await dispatch(FakeDatabase(), context={**VALUES, "name": "private-value" * 20})
    assert "Nombre" in error.value.safe_message
    assert "private-value" not in error.value.safe_message


async def test_forms_use_registered_input_counts_and_only_prepare_data():
    db = FakeDatabase()
    for name in ("budget.create", "savings_goal.create"):
        result = await prepare_form(name, db, UserScope(user_id=UID))
        assert not result.is_error
        assert ACTIONS[name]["inputCount"] == len(ACTIONS[name]["inputs"])
    assert db.calls == []


def test_write_connection_rejects_privileged_role_and_missing_service_secret():
    for patch in (
        {"MCP_ACTIONS_DATABASE_URL": "postgresql://postgres:pw@localhost/db"},
        {
            "MCP_ACTIONS_DATABASE_URL": "postgresql://fluidbank_actions:pw@localhost/db",
            "MCP_TRANSPORT": "http",
        },
    ):
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None, SUPABASE_DATABASE_URL="postgresql://reader:pw@localhost/db", **patch
            )


def test_context_models_cover_every_declared_action():
    assert set(ACTIONS) == set(CONTEXTS)


def test_remote_write_proof_binds_identity_and_all_action_fields():
    import hashlib
    import hmac
    import json

    from supabase_mcp.a2ui_actions.proof import verify_action_proof

    payload = {
        "name": "budget.create",
        "surfaceId": "budget-create",
        "sourceComponentId": "submit",
        "timestamp": "2026-09-13T12:00:00Z",
        "context": VALUES,
        "user_id": UID,
    }
    secret = SecretStr("test-only-secret-for-offline-tests-12345")
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    proof = hmac.new(secret.get_secret_value().encode(), encoded, hashlib.sha256).hexdigest()
    verify_action_proof(secret, proof, payload)
    for changed in (
        {**payload, "user_id": "other"},
        {**payload, "context": {**VALUES, "limit_amount": 999}},
    ):
        with pytest.raises(ActionDispatchError):
            verify_action_proof(secret, proof, changed)
    with pytest.raises(ActionDispatchError):
        verify_action_proof(secret, None, payload)
