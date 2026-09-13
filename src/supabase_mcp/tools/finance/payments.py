"""Upcoming and historical payment MCP tools."""

from fastmcp import Context
from fastmcp.tools import ToolResult

from supabase_mcp.finance_models.payments import (
    BeneficiariesRequest,
    PaymentActivityRequest,
    UpcomingPaymentsRequest,
)
from supabase_mcp.services.finance.payments import (
    get_beneficiaries_data,
    get_payment_activity_data,
    get_upcoming_payments_data,
)
from supabase_mcp.tools.finance._shared import _run


async def get_upcoming_payments(request: UpcomingPaymentsRequest, ctx: Context) -> ToolResult:
    """Próximos cargos y vencimientos / Upcoming charges and due dates.

    Use for future schedules, subscriptions, debts, cards, and payment orders;
    for past activity use get_payment_activity. Úsala para los próximos días.
    """
    return await _run("get_upcoming_payments", request, ctx, get_upcoming_payments_data)


async def get_payment_activity(request: PaymentActivityRequest, ctx: Context) -> ToolResult:
    """Transferencias y órdenes históricas / Historical payment activity.

    Use for recorded activity only; it never executes or confirms movement.
    Para futuros cargos usa get_upcoming_payments.
    """
    return await _run("get_payment_activity", request, ctx, get_payment_activity_data)


async def get_beneficiaries(request: BeneficiariesRequest, ctx: Context) -> ToolResult:
    """Beneficiarios / Beneficiaries.

    Searches safe names, banks, masked last four digits, and status; never
    returns CLABE. Úsala para consultar destinatarios guardados.
    """
    return await _run("get_beneficiaries", request, ctx, get_beneficiaries_data)


__all__ = ["get_beneficiaries", "get_payment_activity", "get_upcoming_payments"]
