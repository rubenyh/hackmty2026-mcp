"""Bounded domain service for allowlisted database-object discovery."""

from __future__ import annotations

from dataclasses import dataclass

from supabase_mcp.database import DatabaseClient
from supabase_mcp.models import AllowedObject

DATABASE_OVERVIEW_MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class DatabaseOverview:
    """Presentation-independent overview of the reflected database allowlist."""

    objects: tuple[AllowedObject, ...]
    total_count: int
    limit: int
    truncated: bool

    def structured_content(self) -> dict[str, object]:
        return {
            "ok": True,
            "objects": [item.model_dump(by_alias=True) for item in self.objects],
            "object_count": len(self.objects),
            "total_count": self.total_count,
            "limit": self.limit,
            "truncated": self.truncated,
        }


def get_database_overview(database: DatabaseClient, limit: int) -> DatabaseOverview:
    """Return a deterministic, bounded view of already-reflected objects."""
    if not 1 <= limit <= DATABASE_OVERVIEW_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {DATABASE_OVERVIEW_MAX_LIMIT}")
    objects = database.list_allowed_objects()
    selected = tuple(objects[:limit])
    return DatabaseOverview(
        objects=selected,
        total_count=len(objects),
        limit=limit,
        truncated=len(objects) > limit,
    )
