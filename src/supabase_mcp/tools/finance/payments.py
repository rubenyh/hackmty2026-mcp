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
    """List the upcoming payments and due dates inside a forward window.

    Returns one dated item per obligation coming up - scheduled cash flows,
    subscription renewals, debt installments, credit-card payments and pending
    payment orders - with amount, currency, due date, status and source, plus
    totals per currency. Use it when the user asks what they have to pay next.
    Payments already made belong to get_payment_activity, and nothing here is
    executed or scheduled.
    """
    return await _run("get_upcoming_payments", request, ctx, get_upcoming_payments_data)


async def get_payment_activity(request: PaymentActivityRequest, ctx: Context) -> ToolResult:
    """List the transfers and payment orders the user already made.

    Returns the historical transfers and payment orders of a period with
    amount, fee, currency, kind, status and dates, filtered by kind and status
    and paginated. Use it to confirm that money was sent or a payment went
    through. Charges still ahead belong to get_upcoming_payments and card
    purchases to get_transactions. It is read-only and moves no money.
    """
    return await _run("get_payment_activity", request, ctx, get_payment_activity_data)


async def get_beneficiaries(request: BeneficiariesRequest, ctx: Context) -> ToolResult:
    """List the saved beneficiaries and payees of the user.

    Returns per saved recipient a safe display name, bank, masked last four
    digits and status, searchable by name fragment and paginated. Use it when
    the user refers to someone they usually send money to. It sends no money
    and never returns CLABE or full account numbers; past transfers belong to
    get_payment_activity.
    """
    return await _run("get_beneficiaries", request, ctx, get_beneficiaries_data)


__all__ = ["get_beneficiaries", "get_payment_activity", "get_upcoming_payments"]
