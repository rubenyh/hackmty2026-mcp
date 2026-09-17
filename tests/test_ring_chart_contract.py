"""The `ring` chart kind must accept and reject exactly what the mobile client does.

The mobile repo owns the shared fixture (`tests/fixtures/chart-contract.json`);
the agent already asserts parity against it. This keeps the MCP's `ChartData`
in the same lockstep, so a ring the MCP emits is never one the client refuses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from supabase_mcp.models import ChartData, RingChartData

_ADAPTER: TypeAdapter[Any] = TypeAdapter(ChartData)


def _mobile_fixtures() -> dict[str, list[dict[str, Any]]]:
    monorepo = Path(__file__).resolve().parents[2]
    path = monorepo / "HackMTY2026_Mobile/tests/fixtures/chart-contract.json"
    if not path.exists():
        pytest.skip("mobile repo not checked out beside this one")
    return json.loads(path.read_text(encoding="utf-8"))


def _with_summary(chart: dict[str, Any]) -> dict[str, Any]:
    # The MCP always writes an accessible summary; the client treats it as
    # optional. Fill it in so the comparison is about the props, not that field.
    return {**chart, "accessibleSummary": chart.get("accessibleSummary", "Resumen accesible.")}


def test_ring_fixtures_accepted_by_the_client_are_accepted_here() -> None:
    rings = [c for c in _mobile_fixtures()["accepted"] if c["kind"] == "ring"]
    assert rings, "the shared fixture should carry at least one ring"
    for chart in rings:
        parsed = _ADAPTER.validate_python(_with_summary(chart))
        assert isinstance(parsed, RingChartData)
        # `max` is the wire name; it round-trips through the alias.
        assert parsed.props.limit == chart["props"]["max"]


def test_ring_fixtures_rejected_by_the_client_are_rejected_here() -> None:
    rings = [c for c in _mobile_fixtures()["rejected"] if c.get("kind") == "ring"]
    assert rings, "the shared fixture should carry at least one rejected ring"
    for chart in rings:
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(_with_summary(chart))


def test_ring_defaults_are_the_clients_not_ours() -> None:
    minimal = {
        "kind": "ring",
        "accessibleSummary": "x",
        "props": {"value": 1, "max": 4, "label": "Mínimo"},
    }
    parsed = _ADAPTER.validate_python(minimal)
    assert isinstance(parsed, RingChartData)
    # Left unset on purpose: the client applies spend / 0.8 / md.
    assert parsed.props.intent is None
    assert parsed.props.warn_at is None
    assert parsed.props.size is None
    # Serialized by alias, so what leaves the MCP is the wire shape.
    assert parsed.model_dump(by_alias=True, exclude_none=True)["props"] == {
        "value": 1.0,
        "max": 4.0,
        "label": "Mínimo",
    }
