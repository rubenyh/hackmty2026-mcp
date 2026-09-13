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
    """Proximos pagos y vencimientos / Upcoming payments and due dates.

    Scheduled charges inside a forward window: subscriptions, debt
    installments, card cutoffs and payment orders. Future only; completed
    payments belong to get_payment_activity. Claves: proximos pagos, pago,
    pagos, vencimiento, vencimientos, suscripcion, suscripciones, upcoming
    payments, due dates, scheduled charges, subscriptions.
    """
    return await _run("get_upcoming_payments", request, ctx, get_upcoming_payments_data)


async def get_payment_activity(request: PaymentActivityRequest, ctx: Context) -> ToolResult:
    """Transferencias y ordenes de pago historicas / Past transfers and payments.

    Transfers and payment orders already recorded. Read-only: it executes,
    schedules and confirms nothing. Charges still ahead belong to
    get_upcoming_payments. Claves: transferencia, transferencias, transferi,
    envie dinero, pagos realizados, transfer, transfers, payment history,
    payments made, sent money.
    """
    return await _run("get_payment_activity", request, ctx, get_payment_activity_data)


async def get_beneficiaries(request: BeneficiariesRequest, ctx: Context) -> ToolResult:
    """Beneficiarios y destinatarios guardados / Saved beneficiaries and payees.

    Safe display name, bank, masked last four digits and status per saved
    recipient. Excludes CLABE and full account numbers, and sends no money.
    Claves: beneficiario, beneficiarios, destinatario, destinatarios,
    contactos guardados, beneficiary, beneficiaries, payee, payees, saved
    recipients.
    """
    return await _run("get_beneficiaries", request, ctx, get_beneficiaries_data)


__all__ = ["get_beneficiaries", "get_payment_activity", "get_upcoming_payments"]
