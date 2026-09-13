"""Bilingual, typed, read-only financial domain tools."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from fastmcp import Context
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from supabase_mcp.errors import SafeMCPError
from supabase_mcp.finance_models import (
    AccountsRequest,
    BankStatementsRequest,
    BeneficiariesRequest,
    BudgetProgressRequest,
    CashFlowRequest,
    CompareDebtScenariosRequest,
    DebtOverviewRequest,
    FinancialAlertsRequest,
    FinancialOverviewRequest,
    PaymentActivityRequest,
    SavingsProgressRequest,
    SpendingAnalysisRequest,
    TransactionDisputesRequest,
    TransactionsRequest,
    UpcomingPaymentsRequest,
)
from supabase_mcp.serialization import to_json_safe
from supabase_mcp.services.finance import (
    analyze_spending_data,
    compare_debt_scenarios_data,
    get_accounts_data,
    get_bank_statements_data,
    get_beneficiaries_data,
    get_budget_progress_data,
    get_cash_flow_data,
    get_debt_overview_data,
    get_financial_alerts_data,
    get_financial_overview_data,
    get_payment_activity_data,
    get_savings_progress_data,
    get_transaction_disputes_data,
    get_transactions_data,
    get_upcoming_payments_data,
)
from supabase_mcp.tools.health import _database

logger = logging.getLogger(__name__)
RequestT = TypeVar("RequestT", bound=BaseModel)


async def _run(
    operation: str,
    request: RequestT,
    ctx: Context,
    handler: Callable[[Any, RequestT], Awaitable[dict[str, Any]]],
) -> ToolResult:
    try:
        data = to_json_safe(await handler(_database(ctx), request))
        return ToolResult(
            content=[
                TextContent(text="Financial data retrieved. / Datos financieros consultados.")
            ],
            structured_content=data,
        )
    except SafeMCPError as exc:
        return ToolResult(
            content=[TextContent(text=exc.safe_message)],
            structured_content={
                "ok": False,
                "error": {"code": exc.code, "message": exc.safe_message},
            },
            is_error=True,
        )
    except SQLAlchemyError as exc:
        logger.warning(
            "Financial tool database failure operation=%s type=%s", operation, type(exc).__name__
        )
        message = (
            "The financial request could not be completed. / "
            "No se pudo completar la consulta financiera."
        )
        return ToolResult(
            content=[TextContent(text=message)],
            structured_content={
                "ok": False,
                "error": {"code": "database_error", "message": message},
            },
            is_error=True,
        )
    except Exception as exc:
        logger.warning("Financial tool failed operation=%s type=%s", operation, type(exc).__name__)
        message = (
            "The financial request could not be completed. / "
            "No se pudo completar la consulta financiera."
        )
        return ToolResult(
            content=[TextContent(text=message)],
            structured_content={"ok": False, "error": {"code": "server_error", "message": message}},
            is_error=True,
        )


async def get_financial_overview(request: FinancialOverviewRequest, ctx: Context) -> ToolResult:
    """Resumen financiero general / General financial overview.

    Use for broad health, monthly summary, balances, budgets, savings, debts,
    obligations, and alerts in one call; do not manually combine narrower tools.
    Úsala para panorama general, resumen mensual o señales preocupantes.
    """
    return await _run("get_financial_overview", request, ctx, get_financial_overview_data)


async def get_accounts(request: AccountsRequest, ctx: Context) -> ToolResult:
    """Cuentas y tarjetas / Accounts and cards.

    Use for balances, safe account names, cards, and latest credit terms; never
    returns CLABE or full card numbers. Úsala para saldos y tarjetas.
    """
    return await _run("get_accounts", request, ctx, get_accounts_data)


async def get_transactions(request: TransactionsRequest, ctx: Context) -> ToolResult:
    """Movimientos específicos / Specific transactions.

    Use for merchants, purchases, latest movements, or filtered lists; for
    aggregate patterns use analyze_spending. Úsala para movimientos concretos.
    """
    return await _run("get_transactions", request, ctx, get_transactions_data)


async def analyze_spending(request: SpendingAnalysisRequest, ctx: Context) -> ToolResult:
    """Patrones de gasto / Spending patterns.

    Use for categories, daily activity, top merchants, and previous-period
    comparison; do not call get_transactions first. Úsala para analizar gastos.
    """
    return await _run("analyze_spending", request, ctx, analyze_spending_data)


async def get_cash_flow(request: CashFlowRequest, ctx: Context) -> ToolResult:
    """Ingresos contra gastos en el tiempo / Income versus expenses over time.

    Use for 3, 6, or 12-month cash-flow trends; for categories use
    analyze_spending. Úsala para comparar ingresos, gastos y neto por mes.
    """
    return await _run("get_cash_flow", request, ctx, get_cash_flow_data)


async def get_budget_progress(request: BudgetProgressRequest, ctx: Context) -> ToolResult:
    """Avance de presupuestos / Budget progress.

    Returns the view's limit, spent, remaining, percentage, dates, and status.
    Devuelve el progreso ya calculado; no recalcula movimientos.
    """
    return await _run("get_budget_progress", request, ctx, get_budget_progress_data)


async def get_savings_progress(request: SavingsProgressRequest, ctx: Context) -> ToolResult:
    """Avance de metas de ahorro / Savings-goal progress.

    Use for target, saved, remaining, percentage, target date, suggested
    contribution, and optional contributions. Úsala para metas de ahorro.
    """
    return await _run("get_savings_progress", request, ctx, get_savings_progress_data)


async def get_debt_overview(request: DebtOverviewRequest, ctx: Context) -> ToolResult:
    """Panorama de deudas y tarjetas / Debt and credit-card overview.

    Use for amounts owed, rates, due dates, utilization, and related scenarios;
    for ranking scenarios use compare_debt_scenarios. El mínimo no es recomendación.
    """
    return await _run("get_debt_overview", request, ctx, get_debt_overview_data)


async def get_upcoming_payments(request: UpcomingPaymentsRequest, ctx: Context) -> ToolResult:
    """Próximos cargos y vencimientos / Upcoming charges and due dates.

    Use for future schedules, subscriptions, debts, cards, and payment orders;
    for past activity use get_payment_activity. Úsala para los próximos días.
    """
    return await _run("get_upcoming_payments", request, ctx, get_upcoming_payments_data)


async def get_financial_alerts(request: FinancialAlertsRequest, ctx: Context) -> ToolResult:
    """Alertas financieras / Financial alerts.

    Use for warnings filtered by kind, account, budget, urgency, and due date.
    Úsala para avisos, riesgos y señales urgentes.
    """
    return await _run("get_financial_alerts", request, ctx, get_financial_alerts_data)


async def get_bank_statements(request: BankStatementsRequest, ctx: Context) -> ToolResult:
    """Estados de cuenta / Bank statements.

    Returns safe metadata and availability; never exposes storage paths, CLABE,
    or invented URLs. Úsala para periodos y saldos de apertura/cierre.
    """
    return await _run("get_bank_statements", request, ctx, get_bank_statements_data)


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


async def get_transaction_disputes(request: TransactionDisputesRequest, ctx: Context) -> ToolResult:
    """Aclaraciones de transacciones / Transaction disputes.

    Returns dispute status with a safe transaction summary and validates every
    identifier against the authenticated user. Úsala para cargos no reconocidos.
    """
    return await _run("get_transaction_disputes", request, ctx, get_transaction_disputes_data)


async def compare_debt_scenarios(request: CompareDebtScenariosRequest, ctx: Context) -> ToolResult:
    """Compara escenarios de deuda / Compare saved debt scenarios.

    Ranks existing scenarios and shows baseline differences; never invents or
    persists scenarios. Úsala solo para comparar escenarios existentes.
    """
    return await _run("compare_debt_scenarios", request, ctx, compare_debt_scenarios_data)


FINANCIAL_TOOLS = (
    get_financial_overview,
    get_accounts,
    get_transactions,
    analyze_spending,
    get_cash_flow,
    get_budget_progress,
    get_savings_progress,
    get_debt_overview,
    get_upcoming_payments,
    get_financial_alerts,
    get_bank_statements,
    get_payment_activity,
    get_beneficiaries,
    get_transaction_disputes,
    compare_debt_scenarios,
)

__all__ = [*(tool.__name__ for tool in FINANCIAL_TOOLS), "FINANCIAL_TOOLS"]
