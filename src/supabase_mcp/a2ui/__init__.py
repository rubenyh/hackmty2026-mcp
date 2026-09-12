"""Reusable A2UI presentation infrastructure for selected MCP tools."""

from supabase_mcp.a2ui.constants import A2UI_BASIC_CATALOG, A2UI_MIME_TYPE, A2UI_VERSION
from supabase_mcp.a2ui.models import SurfaceSpec
from supabase_mcp.a2ui.response import A2UIResponseFactory
from supabase_mcp.a2ui.surfaces import DATABASE_OVERVIEW_SURFACE, SURFACE_REGISTRY

__all__ = [
    "A2UI_BASIC_CATALOG",
    "A2UI_MIME_TYPE",
    "A2UI_VERSION",
    "DATABASE_OVERVIEW_SURFACE",
    "SURFACE_REGISTRY",
    "A2UIResponseFactory",
    "SurfaceSpec",
]
