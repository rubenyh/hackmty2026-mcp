"""Application-only agent-context tool with a fixed data contract."""

from __future__ import annotations

import logging

from fastmcp import Context

from supabase_mcp.errors import InvalidSelectionError
from supabase_mcp.models import PublicError, UserContextResult, UserScope
from supabase_mcp.services.user_context import get_user_context_data
from supabase_mcp.tools._context import database_from_context

logger = logging.getLogger(__name__)


async def get_user_context(scope: UserScope, ctx: Context) -> UserContextResult:
    """Load the authenticated user's fixed turn context; unavailable to the model."""
    try:
        result = await get_user_context_data(database_from_context(ctx), scope)
        return UserContextResult.model_validate(result)
    except InvalidSelectionError as exc:
        return UserContextResult(
            ok=False,
            error=PublicError(code=exc.code, message=exc.safe_message),
        )
    except Exception as exc:
        logger.warning("User context loading failed (%s)", type(exc).__name__)
        return UserContextResult(
            ok=False,
            error=PublicError(
                code="database_error",
                message="The user context could not be loaded.",
            ),
        )
