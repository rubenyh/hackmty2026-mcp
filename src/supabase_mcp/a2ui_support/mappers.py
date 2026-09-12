"""Pure mappings from domain overview results to A2UI data models."""

from supabase_mcp.services.database_overview import DatabaseOverview


def database_overview_data_model(overview: DatabaseOverview) -> dict[str, object]:
    """Map a bounded domain result to the fields bound by the static template."""
    if overview.objects:
        objects_text = "\n".join(
            f"- `{item.schema_name}.{item.table}` · {item.kind}" for item in overview.objects
        )
    else:
        objects_text = "No database objects are currently exposed by the allowlist."
    qualifier = " (limited)" if overview.truncated else ""
    return {
        "title": "Supabase database overview",
        "summary": (
            f"Showing {len(overview.objects)} of {overview.total_count} "
            f"allowlisted objects{qualifier}."
        ),
        "objectsText": objects_text,
        "limit": overview.limit,
    }


def database_overview_fallback(overview: DatabaseOverview) -> str:
    """Create useful text for MCP clients that ignore embedded A2UI resources."""
    if not overview.objects:
        return "No allowlisted database tables or views are currently available."
    names = ", ".join(f"{item.schema_name}.{item.table}" for item in overview.objects)
    suffix = " The result was truncated." if overview.truncated else ""
    return f"Allowlisted database objects ({len(overview.objects)}): {names}.{suffix}"
