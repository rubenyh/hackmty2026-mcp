"""Budget-progress MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.budgets import BudgetProgressRequest
from supabase_mcp.services.finance.budgets import get_budget_progress_data
from supabase_mcp.tools.finance._shared import _run


async def get_budget_progress(request: BudgetProgressRequest, ctx: Context) -> ToolResult:
    """Avance de presupuestos / Budget progress.

    Limit, amount spent, remaining amount, percentage used, period dates and
    status per budget, already calculated by the database. Reports budgets and
    never re-derives spending. Claves: presupuesto, presupuestos, presupuesto
    mensual, limite, cuanto queda, budget, budgets, budget progress, over
    budget, budget limit, remaining budget.
    """
    return await _run("get_budget_progress", request, ctx, get_budget_progress_data)


__all__ = ["get_budget_progress"]
