"""Progressive tool discovery over the growing financial domain catalog.

The model-facing `tools/list` is replaced by FastMCP's native BM25 search
transform, so an LLM receives two synthetic tools (`search_tools` and
`call_tool`) instead of the full schema of every domain tool. Domain tools stay
registered, stay individually specialized, and remain callable: the transform
only changes which definitions are advertised.

```text
tools/list          -> search_tools, call_tool
search_tools(query) -> the few relevant domain tool definitions
call_tool(name, ..) -> the real domain tool, through the normal pipeline
```

Nothing here executes domain logic, filters rows, or relaxes a scope check.
Discovery is advertisement; authorization stays exactly where it already is.
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Sequence
from typing import Any

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.transforms.search import BM25SearchTransform
from fastmcp.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

#: Names of the two synthetic tools the transform publishes. They are the whole
#: model-facing surface, so the middleware and the server tests share them.
SEARCH_TOOL_NAME = "search_tools"
CALL_TOOL_NAME = "call_tool"

#: Conservative result count. BM25 has no stemming, so a wider window mostly
#: adds near-miss tools; five keeps one clear winner plus its neighbours.
SEARCH_MAX_RESULTS = 5

#: Pinned for reachability, not for the model.
#:
#: A hosted deployment fronts this server with a proxy that resolves `tools/call`
#: against the advertised catalog, so on Horizon a tool absent from `tools/list`
#: answers `Unknown tool` however it is addressed - unlike a direct FastMCP
#: server, which happily delegates to it. Callable therefore means advertised,
#: and the three tools the trusted orchestrator invokes by name have to stay on
#: the list: `select_rows` builds the user context every turn, and `a2ui_action`
#: and `a2ui_form` carry the confirmed-action flow the client drives.
#:
#: All three remain `app_only`, so tool search and the `call_tool` proxy still
#: refuse them and a model can neither discover nor invoke them. Pinning widens
#: what the host can address, not what the model can reach. Everything else -
#: every financial capability - is found through search.
ALWAYS_VISIBLE: tuple[str, ...] = ("select_rows", "a2ui_action", "a2ui_form")

#: Longest search query fragment that may reach a debug log line.
_QUERY_LOG_LIMIT = 120

#: BM25 ships no stopword list, so a rare function word is scored as a rare
#: term. "how are my finances" then ranks whichever tool happens to contain
#: "are" above the one that contains "finances". Stripping these from the
#: query — never from the index — leaves ranking to the domain nouns and keeps
#: tool descriptions readable instead of contorted around banned words.
_QUERY_STOPWORDS = frozenset(
    """
    a about after all also am an and any are as at be been being but by can could did do
    does doing done for from get give go got had has have her here him his how i if in into
    is it its just like make many me might more most much must my no not now of off on once
    one only or other our out over own same see she should show so some such than that the
    their them then there these they this those to too up us use used using very was we
    were what when where which while who why will with would you your
    a al algo alguna algunas alguno algunos ante antes aqui asi como con contra cual cuales
    cuando cuanta cuantas cuanto cuantos dame de del desde donde dos el ella ellas ellos en
    entre era eres es esa esas ese eso esos esta estan estas este esto estos fue ha hace
    hacer han hasta hay la las le les lo los mas me mi mis mucha muchas mucho muchos muy
    nos nuestra nuestro o para pero poco por porque que quien quiero se ser si sin sobre
    solo son su sus tambien tengo tener tiene tienen toda todas todo todos tu tus un una
    unas uno unos usar va van ver y ya yo
    """.split()
)


#: Spanish domain vocabulary mapped onto the English tool metadata.
#:
#: Model-facing descriptions are English, but the product speaks Spanish and the
#: orchestrator hands BM25 the user's own words. BM25 matches literal tokens, so
#: "deudas pendientes" would score zero against an English catalog. Translating
#: the QUERY — never the index — keeps retrieval working without stuffing
#: Spanish keywords into what the model reads. Every value below is vocabulary
#: that genuinely appears in a tool description.
_QUERY_LEXICON: dict[str, str] = {
    "abono": "contribution",
    "abonos": "contributions",
    "aclaracion": "dispute",
    "aclaraciones": "disputes",
    "advertencia": "warning",
    "advertencias": "warnings",
    "ahorrar": "savings",
    "ahorro": "savings",
    "ahorros": "savings",
    "alerta": "alert",
    "alertas": "alerts",
    "avance": "progress",
    "aviso": "alert",
    "avisos": "alerts",
    "banco": "bank",
    "beneficiario": "payee beneficiaries",
    "beneficiarios": "payees beneficiaries",
    "cargo": "charge",
    "cargos": "charges",
    "categoria": "category",
    "categorias": "categories",
    "comercio": "merchant",
    "comercios": "merchants",
    "compara": "compare",
    "comparacion": "comparison",
    "comparar": "compare",
    "compra": "purchase",
    "compras": "purchases",
    "corte": "cutoff",
    "credito": "credit",
    "cuenta": "account",
    "cuentas": "accounts",
    "debo": "owe",
    "destinatario": "recipient payee",
    "destinatarios": "recipients payees",
    "deuda": "debt",
    "deudas": "debts",
    "dinero": "money",
    "efectivo": "flow",
    "egresos": "expenses",
    "escenario": "scenario",
    "escenarios": "scenarios",
    "estrategia": "strategy",
    "estrategias": "strategies",
    "flujo": "cash",
    "fraude": "fraudulent",
    "gasta": "spent",
    "gastar": "spend",
    "gaste": "spent",
    "gasto": "spending",
    "gastos": "expenses",
    "guardado": "saved",
    "guardados": "saved",
    "ingreso": "income",
    "ingresos": "income",
    "limite": "limit",
    "mensual": "monthly",
    "mes": "month",
    "meta": "goal",
    "metas": "goals",
    "movimiento": "transaction",
    "movimientos": "transactions",
    "pagar": "pay",
    "pago": "payment",
    "pagos": "payments",
    "panorama": "overview",
    "pendiente": "outstanding",
    "pendientes": "outstanding",
    "presupuesto": "budget",
    "presupuestos": "budgets",
    "proximo": "upcoming",
    "proximos": "upcoming",
    "reclamacion": "dispute",
    "resumen": "overview",
    "riesgo": "risk",
    "saldo": "balance",
    "saldos": "balances",
    "salud": "health",
    "suscripcion": "subscription",
    "suscripciones": "subscription",
    "tarjeta": "card",
    "tarjetas": "cards",
    "transferencia": "transfer",
    "transferencias": "transfers",
    "transferi": "transfers",
    "urgente": "urgent",
    "vencimiento": "due date",
    "vencimientos": "due dates",
}


def _fold(word: str) -> str:
    """Casefold and strip accents so "aclaración" and "aclaracion" agree."""
    stripped = unicodedata.normalize("NFKD", word.strip(".,;:!?¿¡'\"").casefold())
    return "".join(char for char in stripped if not unicodedata.combining(char))


def _domain_terms(query: str) -> str:
    """Keep the financial vocabulary of a query and express it in English.

    Function words are dropped and Spanish domain words are replaced by the
    English terms the catalog actually uses. Falls back to the original text
    when a query is nothing but stopwords, which keeps a degenerate query
    behaving exactly as it does upstream.
    """
    kept = [
        _QUERY_LEXICON.get(folded, word)
        for word in query.split()
        if (folded := _fold(word)) not in _QUERY_STOPWORDS
    ]
    return " ".join(kept) if kept else query


def app_only(meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Declare a tool host/app-only so the model can neither find nor call it.

    FastMCP reads the MCP Apps `_meta.ui.visibility` declaration in the search
    catalog and in the `call_tool` proxy, which are the two surfaces a host
    cannot filter. Tools marked here keep working for the trusted orchestrator,
    which calls them by name over the ordinary MCP pipeline.
    """
    ui = dict((meta or {}).get("ui", {}))
    ui["visibility"] = ["app"]
    return {**(meta or {}), "ui": ui}


class LoggedBM25SearchTransform(BM25SearchTransform):
    """`BM25SearchTransform` with stopword-filtered queries and debug logging.

    Ranking, indexing and result serialization stay entirely upstream; this
    subclass only normalizes the incoming query and records the outcome.
    """

    async def _search(self, tools: Sequence[Tool], query: str) -> Sequence[Tool]:
        matches = await super()._search(tools, _domain_terms(query))
        logger.debug(
            "tool search candidates=%d matches=%d names=%s query=%r",
            len(tools),
            len(matches),
            ",".join(tool.name for tool in matches) or "none",
            query[:_QUERY_LOG_LIMIT],
        )
        return matches


class DiscoveryLoggingMiddleware(Middleware):
    """Record which tool a discovery call selected, never its arguments."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        if name == CALL_TOOL_NAME:
            arguments = context.message.arguments or {}
            target = arguments.get("name")
            logger.debug(
                "discovery proxy selected tool=%s",
                target if isinstance(target, str) else "invalid",
            )
        elif name == SEARCH_TOOL_NAME:
            logger.debug("discovery search requested")
        return await call_next(context)


def build_tool_search_transform(
    *,
    max_results: int = SEARCH_MAX_RESULTS,
    always_visible: Sequence[str] = ALWAYS_VISIBLE,
) -> BM25SearchTransform:
    """Build the BM25 discovery transform used by the server."""
    return LoggedBM25SearchTransform(
        max_results=max_results,
        always_visible=list(always_visible),
        search_tool_name=SEARCH_TOOL_NAME,
        call_tool_name=CALL_TOOL_NAME,
    )
