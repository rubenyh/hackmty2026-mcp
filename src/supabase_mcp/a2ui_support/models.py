"""Small internal models for A2UI presentation registration."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SurfaceSpec:
    """Connect one stable surface identifier to its packaged MCP resource."""

    surface_id: str
    resource_uri: str
    template_name: str
    title: str
    description: str
