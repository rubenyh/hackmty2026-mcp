# Architecture

## Scope

The repository implements a Model Context Protocol server over Supabase PostgreSQL. Its main pool exposes a deliberately small, typed, read-only query surface and A2UI v0.9.1 presentation layer. It also assembles owned records for four stateless financial predictions and calls the sibling Models API through one shared HTTP client. A separate optional `fluidbank_actions` pool can invoke one fixed SQL dispatcher for explicitly confirmed financial actions. The repository does not include an LLM agent, a renderer, application authentication, arbitrary SQL, or general database mutation.

```text
MCP client
    -> FastMCP transport
    -> BM25 tool-search transform   (tools/list -> search_tools + call_tool)
    -> typed tool
    -> domain service / DatabaseClient
    -> A2UI mapper
    -> A2UIResponseFactory
    -> ToolResult
         -> fallback text
         -> structured domain data
         -> EmbeddedResource updateDataModel
         -> _meta.ui

MCP client
    -> resources/read
    -> cached static A2UI surface template

DatabaseClient
    -> SQLAlchemy async engine / Psycopg
    -> Supabase PostgreSQL

prediction tool
    -> PredictionService
         -> DatabaseClient (ownership-scoped source records)
         -> InferenceClient (normalized identity-free request)
    -> Models FastAPI
```

The server supports stdio and Streamable HTTP. Stdio is the default and is suitable for a client-managed local subprocess. HTTP listens on loopback by default and is not production-secure by itself.

## Repository map

```text
src/
  supabase_mcp/
    __init__.py       Package marker
    config.py         Environment parsing, normalization, and validation
    database.py       Engine lifecycle, reflection, query construction, and execution
    discovery.py      BM25 tool-search transform, app-only visibility, discovery logging
    errors.py         Internal safe error types
    inference.py      Shared typed httpx client and sanitized inference failures
    models.py         Strict generic tool inputs and structured results
    finance_models/   Strict financial and inference contracts grouped by domain
    serialization.py  PostgreSQL-to-JSON-safe conversion
    server.py         Event-loop setup, FastMCP lifespan, registration, and entry point
    services/
      database_overview.py  Bounded presentation-independent overview use case
      user_context.py       Fixed application-context reads for the orchestrator
      finance/        Financial rules, coordinated reads, and prediction assembly
    a2ui_support/
      constants.py    v0.9.1, MIME, catalog, action, and stable URI identifiers
      models.py       Immutable SurfaceSpec
      validation.py   Official SDK validation plus local surface invariants
      surfaces.py     Central validated surface/template registry and cache
      response.py     Reusable ToolResult/updateDataModel composition
      mappers.py      Pure domain-to-data-model and fallback mappings
      actions.py      Typed action context and explicit handler allowlist
      catalogs/
        banking_view.schema.json  Canonical Finance v2 BankingView contract
      templates/
        database_overview.json  Static createSurface/updateComponents messages
        financial_view.json     Stable BankingView/Button composition
    tools/
      _context.py     Internal lifespan dependency lookup
      a2ui.py         Overview, generic action/error, and resource handlers
      finance/        Thin financial MCP handlers and explicit registration tuple
      schema.py       Allowlisted object discovery and description
      user_context.py Fixed app-only context handler; no caller-selected query
scripts/
  seed_demo_data.py  Idempotent demo-data seeder (writes via service-role key, bypasses RLS)
tests/                Offline A2UI unit, packaging, and FastMCP protocol tests
.env.example        Placeholder-only server configuration
README.md           Operator and client-facing usage
AGENTS.md           Coding-agent contribution rules
pyproject.toml      Dependency and tool configuration
Dockerfile          Container definition
uv.lock             Locked dependency graph
```

No `app_agent/` or `sql/` directory is present. Hatch packages `src/supabase_mcp/`, including JSON templates under the package, and the installed `supabase-mcp` command calls `supabase_mcp.server:main`.

## Financial domain organization

Financial code is split into matching model, service, and tool modules. The package
`__init__.py` files are compatibility facades for the former
`supabase_mcp.finance_models`, `supabase_mcp.services.finance`, and
`supabase_mcp.tools.finance` import paths. Shared ownership-safe selection, period,
currency, and cursor helpers live in `services/finance/_shared.py`; shared request
bases and value objects live in `finance_models/_shared.py`.

| Domain | Tool module | Service module | Models module | Responsibility |
|---|---|---|---|---|
| Accounts | `tools/finance/accounts.py` | `services/finance/accounts.py` | `finance_models/accounts.py` | Accounts, masked cards, credit terms, and statement metadata |
| Expenses | `tools/finance/expenses.py` | `services/finance/expenses.py` | `finance_models/expenses.py` | Transactions, spending analysis, and disputes |
| Cash flow | `tools/finance/cash_flow.py` | `services/finance/cash_flow.py` | `finance_models/cash_flow.py` | Monthly income, expenses, and net series |
| Budgets | `tools/finance/budgets.py` | `services/finance/budgets.py` | `finance_models/budgets.py` | Stored budget-progress projections |
| Savings | `tools/finance/savings.py` | `services/finance/savings.py` | `finance_models/savings.py` | Savings goals and optional contributions |
| Debts | `tools/finance/debts.py` | `services/finance/debts.py` | `finance_models/debts.py` | Debt/card overview and saved scenario comparison |
| Payments | `tools/finance/payments.py` | `services/finance/payments.py` | `finance_models/payments.py` | Upcoming obligations, payment activity, and beneficiaries |
| Financial health | `tools/finance/financial_health.py` | `services/finance/financial_health.py` | `finance_models/financial_health.py` | Cross-domain overview and financial alerts |
| Predictions | `tools/finance/predictions.py` | `services/finance/predictions.py` | `finance_models/predictions.py` | Semantic prediction inputs, owned-record normalization, and typed inference responses |

Location rule:

- Change an MCP name, description, parameter boundary, or handler delegation in
  `tools/finance/<domain>.py`.
- Change a calculation, aggregation, or coordinated database read in
  `services/finance/<domain>.py`.
- Change a financial Pydantic schema, enum, or value object in
  `finance_models/<domain>.py` or the narrowly shared `_shared.py`.
- Change the public financial registration set or order in
  `tools/finance/__init__.py`; `server.py` registers only that explicit tuple.

## Demo schema and seed data

`scripts/seed_demo_data.py` is a standalone utility, outside the `supabase_mcp` package, that populates the allowlisted demo tables (`users`, `accessibility_preferences`, `accounts`, `transactions`, `subscriptions`, `transfers`) created by the `create_demo_banking_schema` and `add_transfers_and_cash_flow` migrations, plus the read-only `monthly_cash_flow` view. Every table has row-level security enabled; `mcp_reader` (see below) can only `SELECT`. The script authenticates with the Supabase service-role key, which bypasses RLS, and is idempotent: every row uses a UUID derived deterministically from a stable slug (`uuid5`), so re-running it upserts instead of duplicating. It requires the `seed` extra (`pip install -e ".[seed]"`) and reads `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` from `.env` — neither variable is read by the MCP server itself.

`transfers` retains the legacy simulated movement between two accounts belonging to the same user. Confirmed A2UI transfers use `payment_orders` instead: the fixed SQL dispatcher validates ownership and balance, updates the source and destination balances, and records paired debit/credit `transactions`. A saved beneficiary is executable only when `linked_account_id` points to a verified FluidBank account; `credited_account_id` records the actual receiving account on the order. External contacts remain read data because this MVP has no external-bank payment rail. The balance changes, ledger rows, order, and idempotency receipt commit atomically through the dedicated action role.

`monthly_cash_flow` answers "income vs. expenses" directly: one row per account per calendar month, summing `transactions.amount` by `direction` (`credit` = income, `debit` = expenses) plus a `net` column. It's created `WITH (security_invoker = true)` so it inherits the querying role's RLS instead of the view owner's privileges, and `mcp_reader` has an explicit `GRANT SELECT` on it (views need that in addition to RLS).

The `mcp_reader` Postgres role is a dedicated, `SELECT`-only login created directly in Supabase. The action migration versions the policies needed by the A2UI form tables. `DatabaseClient` sets the verified subject locally in every scoped read transaction, and those policies compare it with each row's owner in addition to the query's mandatory ownership predicate. `SUPABASE_DATABASE_URL` uses the session pooler (`aws-0-ca-central-1.pooler.supabase.com:5432`, username `mcp_reader.<project_ref>`) rather than the direct `db.<ref>.supabase.co` host, which is IPv6-only and fails to resolve on IPv4-only networks.

## Configuration boundary

`Settings` uses `pydantic-settings`, reads process environment variables plus a local `.env`, ignores unrelated variables, and validates:

- a required PostgreSQL URL using the `postgres`, `postgresql`, or `postgresql+psycopg` scheme;
- TLS modes `require`, `verify-ca`, or `verify-full` when `sslmode` is supplied;
- one or more allowed schemas and an exact, possibly empty, table/view allowlist;
- PostgreSQL-like identifiers and unique normalized `(schema, object)` pairs;
- positive default and maximum row limits, with a maximum cap of 10,000;
- a statement timeout from 100 through 60,000 milliseconds;
- optional paired `INFERENCE_API_URL` and secret `INFERENCE_API_KEY` settings;
- total inference timeout from over 0 through 120 seconds and connect timeout from over 0 through 30 seconds, with connect not exceeding total;
- `stdio` or `http` transport, a non-empty host, a valid TCP port, and an enumerated log level.

Unqualified allowlist entries are accepted only when exactly one schema is configured. `sqlalchemy_url()` normalizes accepted URLs to the async Psycopg dialect and adds `sslmode=require` when absent. The unmasked URL is used only to construct the engine and must never be logged.

## Server lifecycle and transports

`supabase_mcp.server` selects `WindowsSelectorEventLoopPolicy` on Windows before importing FastMCP or database modules. This ordering is required by Psycopg's async implementation.

FastMCP's lifespan creates one shared `DatabaseClient` and one shared `InferenceClient`, starts them before serving requests, makes a process-scoped `PredictionService` available through the tool context, and disposes both clients during shutdown. Missing inference configuration does not disable unrelated database tools; a prediction call returns a typed configuration error. The module registers the fixed app-only user-context handler, schema metadata handlers, A2UI handlers, and financial domain tools. It publishes the corresponding A2UI presentation templates as read-only resources.

`main()` selects stdio unless `MCP_TRANSPORT=http`. HTTP uses the configured host and port; FastMCP exposes its MCP endpoint at `/mcp`. The service itself adds no authentication, authorization middleware, reverse-proxy TLS, rate limiting, or tenant isolation.

Importing `supabase_mcp.server` constructs and registers the module-level `mcp` object but does not call `load_settings()`, create an engine, enter the lifespan, connect to PostgreSQL, or start a transport. This makes package imports and Horizon's file-based inspection safe without build-time secrets. Direct execution remains isolated behind the `if __name__ == "__main__"` guard.

The internal A2UI integration package is named `a2ui_support`, rather than `a2ui`, because FastMCP's file-based loader temporarily places `src/supabase_mcp` on the import path. Reusing the external SDK's top-level name caused `from a2ui...` to resolve to the internal package during `fastmcp inspect`, producing a circular import. The distinct package name keeps file-based and installed-package imports equivalent.

## Packaging and Horizon deployment

Hatchling builds the `src/supabase_mcp` package into the wheel, including both static A2UI templates and the packaged Finance Catalog JSON. Runtime imports use the installed `supabase_mcp` package and do not depend on a manually configured `PYTHONPATH`. Python 3.12 satisfies the declared `>=3.11` requirement. Runtime libraries imported by the package are declared in `[project.dependencies]`; test and build tooling remains in the development dependency group.

The sdist target uses an explicit source allowlist. This prevents local virtual environments, build directories, `.env`, caches, and other untracked workstation files from being copied into release artifacts. Horizon generates its own runtime image from `pyproject.toml`, so the repository `Dockerfile` is not part of this deployment path and remains unchanged.

Horizon must use the repository directory containing `pyproject.toml` as its project root, Python 3.12, `pyproject.toml` as its dependency file, and `src/supabase_mcp/server.py:mcp` as its entrypoint. `SUPABASE_DATABASE_URL` is injected at runtime. `MCP_ALLOWED_TABLES` stays deny-all when empty; deployments that expose data must configure it explicitly, and should explicitly configure `MCP_ALLOWED_SCHEMAS` as well. Horizon owns the hosted transport and does not invoke `main()`.

## Database lifecycle and least privilege

`DatabaseClient` owns one SQLAlchemy async engine with a small bounded pool (`pool_size=3`, `max_overflow=2`, five-second pool timeout, and connection pre-ping). On startup it reflects only exact allowlisted tables and views. A non-empty allowlist fails startup if an object is missing, inaccessible, or cannot be reflected. An empty allowlist performs no reflection and exposes no row-selection surface.

Every database read opens a transaction and executes:

1. `SET TRANSACTION READ ONLY`.
2. A transaction-local PostgreSQL `statement_timeout` through `set_config`.
3. The bounded selection statement.

These application controls complement, rather than replace, database controls. Deployments must use a dedicated login with only `CONNECT`, schema `USAGE`, explicit `SELECT`, and suitable Row Level Security policies. The role must not own protected tables, have `BYPASSRLS`, or use Supabase administrative/service-role credentials.

Startup failures are logged only by bounded operation name and exception class. Exception text and stack traces are intentionally excluded so connection and SQL details cannot escape through platform logs.

## Query construction

Clients cannot provide SQL or a general row-selection request. Internal services construct a `SelectRequest` naming a reflected schema/object, a mandatory typed `UserScope`, optional reflected columns, typed filters, typed ordering, an optional limit, and a non-negative offset. Pydantic models forbid unknown fields. The app-only context handler owns a fixed table set and accepts only trusted scope.

`TABLE_USER_SCOPES` is the explicit ownership registry. `users.id`, `accessibility_preferences.user_id`, `accounts.user_id`, `subscriptions.user_id`, and `transfers.user_id` are direct scopes. `transactions.account_id` and `monthly_cash_flow.account_id` are scoped with a parameterized correlated `EXISTS` through `accounts.id` and `accounts.user_id`. The canonical scope predicate is added before all business filters, so SQLAlchemy combines them with `AND`. Unknown/non-demo UUIDs, missing ownership metadata, model-style ownership filters, and allowlisted objects without a registry entry fail with sanitized errors instead of returning rows.

Supported filter operators are `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `like`, `ilike`, and `is_null`. Ordinary operators require a JSON scalar; `is_null` requires a boolean; `in` requires a non-empty list of at most 100 JSON scalars. SQLAlchemy builds bound expressions for values.

The effective limit is the request limit or `MCP_DEFAULT_LIMIT` and cannot exceed `MCP_MAX_LIMIT`. The query fetches one additional row to set `truncated`, then returns at most the effective limit. Explicit ordering is applied in request order; otherwise primary-key columns provide deterministic ordering when present.

## Progressive tool discovery

Thirty tools are registered, twenty of them financial, and that catalog is
expected to keep growing. Sending every schema on every request wastes context,
slows the turn, and degrades selection, so `supabase_mcp.discovery` installs
FastMCP's native `BM25SearchTransform` as the last transform on the server.
The model-facing portion of `tools/list` then carries exactly two synthetic
tools, alongside three pinned app-only handlers used by the trusted host:

```text
search_tools(query)         ranked, self-contained definitions from the catalog
call_tool(name, arguments)  executes one discovered tool
```

`ALWAYS_VISIBLE` pins three tools — `get_user_context`, `a2ui_action` and
`a2ui_form` — and pins them for reachability, not for the model. A hosted
deployment fronts this server with a proxy that resolves `tools/call` against
the advertised catalog, so on Horizon an unadvertised tool answers `Unknown
tool` however it is addressed, while a direct FastMCP server delegates to it
happily. Callable therefore means advertised, and those three are the ones the
trusted orchestrator invokes by name: `get_user_context` builds the fixed user context on
every turn, and the other two carry the confirmed-action flow. All three stay
`app_only`, so search and the proxy still refuse them — pinning widens what the
host can address, never what the model can reach.

Nothing else is pinned, and a fourth name needs a written architectural reason.
The combination to avoid is app-only *and* unpinned: such a tool is unreachable
by name and refused by the proxy, which is exactly how user context broke in
production once. `test_every_orchestrator_driven_tool_is_still_reachable` guards
that invariant.

Discovery is advertisement only. Registration, lifespan, services, database
filtering, user scoping, A2UI contracts, structured results and error handling
are unchanged; a hidden tool is still reached by name over the ordinary MCP
pipeline, which is how the trusted orchestrator reads its fixed user context
and drives the confirmed-action flow through `a2ui_form`.

Two properties of that pipeline matter for safety. `call_tool` dispatches
through `ctx.fastmcp.call_tool`, so middleware — including
`FinancialValidationMiddleware` — auth and per-component checks all run exactly
as they do for a direct call; there is no reflection and no direct invocation of
the underlying Python function. And both search and the proxy read the catalog
through `CatalogTransform.get_tool_catalog`, which drops any component declaring
`_meta.ui.visibility = ["app"]`. `discovery.app_only()` sets that declaration,
merging it into an existing `ui` block so an A2UI resource link survives, and the
server applies it to `get_user_context`, `list_allowed_tables`, `describe_table`,
`present_financial_view`, `chat_message`, `a2ui_action`,
`a2ui_error` and `a2ui_form`. Those nine were never offered to a model, so
discovery must not become the thing that offers them: a generic row reader — or
a tool that applies confirmed financial actions — appearing in search results is a wider
boundary, not a narrower context.

Ranking quality is a property of the descriptions. BM25 indexes tool names,
descriptions and parameter names/descriptions, and carries no stemming and no
stopword list, so a rare function word scores like a rare domain term and
`"how are my finances"` ranks whichever tool happens to contain `are`.
`LoggedBM25SearchTransform` therefore strips function words from the incoming
query before delegating upstream — never from the index — and every financial
description is written declaratively, with an explicit boundary against its
nearest neighbour (`get_transactions` records against `analyze_spending`
aggregates, `get_cash_flow` trend against `analyze_spending` breakdown,
`get_upcoming_payments` future against `get_payment_activity` past,
`get_debt_overview` amounts against `compare_debt_scenarios` ranking) and a
bilingual keyword tail covering the singular and plural forms a user types.
Tags are registered for filtering and operator tooling; they are not indexed and
do not affect ranking.

FastMCP 4.0.3 has client-side handling for `notifications/tools/list_changed`
but emits none from the server, and this server registers its whole catalog at
import. No cache invalidation was added: the model-facing list is two synthetic
tools that never change, and search results are read live from the catalog on
every query, so a tool added by a redeploy is discoverable immediately.

Discovery logging is debug-level and structural: `LoggedBM25SearchTransform`
records candidate count, match count, matched names and a 120-character query
fragment, and `DiscoveryLoggingMiddleware` records the tool name a `call_tool`
selected. Neither logs arguments, rows, credentials or authorization headers.

## Tool contracts and errors

- `get_user_context` returns only the fixed application context needed for one authenticated turn; it accepts no source, column, filter, ordering, pagination, or SQL fields.
- `list_allowed_tables` returns only successfully reflected allowlisted tables/views and a count.
- `describe_table` returns cached names, SQL types, nullability, and primary-key flags.

Known request failures use stable public codes such as `object_not_allowed`, `column_not_allowed`, `limit_exceeded`, and `invalid_request`. Unexpected failures are reduced to sanitized `server_error`, `database_error`, or `database_unavailable` results. Logs record an operation label and exception class, not credentials or row bodies.

Visualization query failures raised by the database driver use the actionable, sanitized `database_error` result rather than falling through to a generic server failure. Protocol responses never include driver text, SQL statements, connection details, or stack traces.

The twenty financial tools share a stricter execution boundary. Every controlled
failure is a `ToolResult` with `isError: true`; its fallback text is the same
sanitized JSON object exposed in `structuredContent`. The stable codes are
`VALIDATION_ERROR`, `INVALID_DATE_RANGE`, `INVALID_CURSOR`, `USER_SCOPE_ERROR`,
`NOT_FOUND`, `DATABASE_UNAVAILABLE`, `DATABASE_TIMEOUT`,
`DATABASE_PERMISSION_ERROR`, `DATABASE_QUERY_ERROR`, `DATA_MAPPING_ERROR`, and
`INTERNAL_ERROR`. Prediction-specific codes distinguish missing configuration,
timeout, network/model unavailability, 401/403 authentication, 409 version mismatch,
422 contract mismatch, and malformed/unexpected responses. Each error also names the tool and internal operation, identifies
the failing layer, marks retryability, offers a bounded suggestion, and carries a
correlation ID. A FastMCP middleware validates only the registered financial
request envelopes before dispatch so argument failures retain this structure and
FastMCP does not log the rejected financial payload.

Financial invocation logs contain the tool, operation, correlation ID, duration,
outcome, and a safe row count when available. Failure logs retain traceback frames
and the real exception type while replacing exception text, which may contain SQL,
parameters, credentials, or connection details. Financial row bodies are never
logged. Driver SQLSTATE classification distinguishes statement cancellation/timeouts,
connection failures, permission failures, and other query failures.

Literal-narrowed period request models compare the public period value rather than
enum identity. `custom` therefore requires both dates and rejects inverted ranges
for transactions, spending analysis, and cash flow. Dispute reads apply their
optional period to `created_at` and do not issue an unfiltered transaction lookup
when the dispute page is empty.

Serialization preserves primitive JSON values, stringifies UUIDs and decimals, emits ISO-8601 date/time strings, converts enums through their values, Base64-encodes bytes, and recursively handles mappings and sequences. Unknown values fall back to strings.

## Prediction boundary

The four model-facing capabilities are `forecast_cash_balance`, `predict_savings_goal`,
`forecast_recurring_charges`, and `detect_transaction_anomalies`. Their public request models
contain trusted `scope`, one account or goal UUID, and only the applicable horizon/candidate
period. Raw transactions, scheduled flows, and contributions are not accepted from the LLM.

`PredictionService` obtains account currency/balance and related rows through the same
`DatabaseClient.select_domain_rows` and ownership helpers used by the existing finance services.
Cash balance reads `accounts`, `transactions`, and `scheduled_cash_flows`; savings-goal prediction
reads `savings_goals`, `savings_contributions`, `accounts`, and `transactions`; recurring charges
and anomalies read `accounts` and `transactions`. Exact account and goal lookups fail closed when
the scoped row is absent. Every database request retains the canonical `UserScope`, including
relationship filters.

The assembler converts stored amounts to finite positive magnitudes and keeps the authoritative
direction so the Models API derives `credit`/`income` as positive and `debit`/`expense` as negative.
It generates a UUID correlation ID and aware UTC `as_of` for every inference request, excludes
identity and session fields by construction, sorts all histories chronologically, and limits each
history collection to the most recent 500 rows (or the lower configured `MCP_MAX_LIMIT`). This is
the centralized bounded default because the Models contract defines a 10,000-record maximum but
no history window; no additional date window is invented. Scheduled flows are limited to the
selected cash forecast horizon, and anomaly candidates are the requested last 1–90 days.

`InferenceClient` owns one `httpx.AsyncClient` for the process, sends only
`Authorization: Bearer <INFERENCE_API_KEY>` to the configured base URL, and validates each response
against a model-specific strict Pydantic contract plus matching `request_id`. It never receives the
user's Supabase bearer token. Error handling does not parse or expose remote error bodies and never
falls back to locally fabricated predictions. A successful tool returns the complete structured
model response; presentation remains the Agent/A2UI responsibility.

## A2UI presentation boundary

A2UI is an optional presentation layer over MCP, not a database or authorization layer. `database_overview`, `visualize_allowed_data`, and `present_financial_view` use it. Normal MCP tools continue returning their existing typed results without inheriting from an A2UI base class.

`CatalogRegistry` loads and caches the Basic, packaged Finance v1, and assembled Finance v2 schemas with `importlib.resources`, rejecting duplicate/unknown IDs or malformed catalogs at import. `SurfaceRegistry` maps each surface ID and resource URI to exactly one catalog and template. Registration rejects duplicates or malformed templates, verifies v0.9.1, catalog/surface identity, ordering, unique component IDs, `root`, and local component references, then runs the matching official SDK validator. Validated serialized templates are served without consulting PostgreSQL.

`database_overview` calls a bounded domain service over `DatabaseClient.list_allowed_objects()`. It exposes cached schema metadata only—no samples, row counts, totals, or aggregates—so it does not receive a user scope. The domain result has no A2UI dependency. A pure mapper produces a small data model for the template. `A2UIResponseFactory` converts it to a validated `updateDataModel` with `path: "/"`, adds a text fallback, preserves a detached JSON-safe domain result in `structuredContent`, embeds the A2UI update using `application/a2ui+json` and `Annotations(audience=["user"])`, and adds the same `_meta.ui` resource link used in the static tool definition. It can also update a validated absolute JSON Pointer without rebuilding the layout.

The static template contains only `createSurface` and `updateComponents`. It binds text and action context to the dynamic model and contains no database values. The dynamic tool response contains only `updateDataModel`; clients may cache the static template independently.

### Finance chart surface

`CatalogRegistry` allowlists and caches the Basic and Finance v1 validators, rejects duplicate or unknown IDs, and fails import on malformed packaged schemas. Every `SurfaceSpec` declares exactly one catalog. `database_overview.json` remains unchanged on Basic and is not a component registry. `data_chart.json` is a separate static surface at `a2ui://finance/data-chart`; Finance v1 exposes only `Text`, `Button`, `Card`, `Column`, and `Chart`.

`visualize_allowed_data` accepts a strict scope/source/filter/order/limit request plus an `area` or `heatmap` column mapping. It resolves only reflected allowlisted identifiers, reuses parameterized `SelectRequest` queries, fetches only required columns, rejects ownership identifiers as chart data, verifies value columns are numeric, applies deterministic ordering, and caps raw rows at 240 for area or 500 for heatmap. Rows with null required values are omitted and counted; malformed dates, duplicate labels/dates, non-finite values, and values outside the chart range fail with safe errors. Its static definition and successful runtime result use identical `_meta.ui`; fallback text and structured domain content are independent of the embedded dynamic update.

The wire `Chart` owns a whole-object binding and a strict discriminator: `{kind: "area", accessibleSummary?, props}` or `{kind: "heatmap", accessibleSummary?, props}`. It requires unique stable area series IDs and bounded data, and accepts no callback, formatter, style, URL, JSX, component name, or generic object. Future catalog components require an SDK-valid versioned schema, an explicit client adapter, a synchronized agent schema copy, parity fixtures, and package tests.

### Finance v2 BankingView surface

MCP is the authoritative source of `https://fluidbank.app/a2ui/catalogs/finance/v2`. `CatalogRegistry` builds it deterministically from Finance v1 and the packaged canonical `banking_view.schema.json`, adding only `BankingView`. The schema preserves the 13 discriminated financial intents, their bounded intent-specific properties, and the common empty-state contract. Unknown fields are rejected, including arbitrary styling. The official SDK validates literal BankingView data before a response is built.

`present_financial_view` is an optional generic validation/resource factory for MCP callers. Its request contains a BankingView value, bounded action label, and bounded target intent; it does not retrieve data or decide which financial semantics to use. The Agent may construct the same messages locally after interpreting MCP results, but must use this exact MCP-owned contract. The registered `financial-view` template is a complete flat graph with stable IDs: `root` (`Column`), `banking_view`, `request_financial_view_label`, and `request_financial_view_button`. Local template validation additionally rejects references to components outside the surface. One dynamic `updateDataModel` supplies the view and action values.

The payment-card contract is part of Finance v2, not a separate component. A `PaymentCard` object - `cardId`, `cardName`, `cardType`, `network`, `lastFour`, `status`, and optional `expires` (`YYYY-MM`) and `accountId` - appears as `cards` on `financial-summary`, and as `card` on `credit-card` and `card-security`. It is the masked projection of `public.cards`: the schema has no property for a full card number, CVV, expiry day, or cardholder document, and `additionalProperties: false` rejects any attempt to add one. `financial-summary` therefore answers a balance question with the account totals *and* the plastic behind them, without a second catalog component or a second retrieval contract.

`credit-card` additionally accepts the bounded `credit_card_terms` projection: `creditLimit`, `statementBalance`, `cutoffDate`, `annualInterestRate`, and `catPercentage`. Rates are percentage points bounded to 0-1000, matching the database check constraint rather than a fraction. Every one of these properties is optional, so a deployment without `credit_card_terms` rows keeps sending the view it sends today.

`financial-summary` requires `totalOwnedBalance` and `spending-analysis` requires `totalSpent`. Both totals are computed by the producer, never by the renderer, so a truncated list of accounts or categories can never silently change the headline number.

`visualize_allowed_data` remains unchanged and presentation-independent in `structuredContent`. The Agent may call it more than once and combine returned `chart` objects into one BankingView payload, such as `spending-analysis`; no MCP retrieval call selects a BankingView intent, and no last-result-wins behavior is introduced in the data service.

## A2UI actions and errors

There is one generic `a2ui_action` tool. The client action retains exactly `name`, `surfaceId`, `sourceComponentId`, `timestamp`, and `context`; the tool accepts optional server-supplied `trustedScope` separately. `ActionRegistry` maps a fixed name to a fixed handler and strict Pydantic context model. Registration verifies that the action and source component occur in the registered template. Dispatch verifies the timestamp, surface, component, context, and any required trusted scope before calling the handler. It never uses `eval`, dynamic imports, or input-driven attribute lookup.

`refresh_database_overview` remains read-only and bounded to 100 objects. `request_financial_view` is bound only to `financial-view` / `request_financial_view_button`, requires trusted `{user_id}` scope, and accepts the 13-value intent plus optional `accountId`, `startDate`, `endDate`, and `period`. Strict context rejects identity fields. Its normalized result keeps the original five-field action, the semantic request, and trusted scope separate; it performs no retrieval and selects no chart.

The generic `a2ui_error` handler recognizes `VALIDATION_FAILED`, returns a safe acknowledgement, and logs only bounded structural metadata: whether the error is a validation failure, whether the surface is known, path presence, and message length. It does not log or echo the client-provided code, message, path, stack trace, rows, or credentials.

## Catalog support and negotiation

The server supports exactly A2UI `v0.9.1` with the official Basic Catalog, `https://fluidbank.app/a2ui/catalogs/finance/v1`, and `https://fluidbank.app/a2ui/catalogs/finance/v2`; inline and all other catalogs are rejected. `a2ui-agent-sdk` 0.5.x supplies the bundled schema machinery. Finance schemas are loaded with `importlib.resources`, validated at import, and cached. Local validation supplements, rather than replaces, the SDK for registered-surface and catalog consistency.

A2UI recommends selecting catalogs from custom client capabilities during MCP `initialize`. Inspection of FastMCP 4.0.3's documented public server APIs found no stable hook that exposes arbitrary initialization capabilities to these typed handlers with session-scoped storage. The server therefore does not implement or claim initialize-time catalog negotiation and does not depend on FastMCP internals or monkeypatches. Controlled clients may advertise and recognize the fixed allowlist; all other clients retain the text and `structuredContent` fallback. Per-call A2UI capability metadata is likewise not used as a substitute for a verified session negotiation API.

## Security boundary and non-goals

The safety model is layered:

- PostgreSQL role grants define the database permissions; this MVP adds no RLS or per-user database authorization.
- Canonical demo-user scoping is application-level filtering and is not a production authorization boundary.
- Configuration narrows exposure to named schemas and objects.
- Reflection narrows selectable identifiers to known columns.
- Typed inputs and SQLAlchemy binding prevent arbitrary statements and value interpolation.
- Read-only transactions, timeouts, pooling bounds, and row limits constrain execution.
- Structured results and sanitized errors constrain the MCP boundary.

Explicit non-goals are arbitrary SQL, caller-selected writes, general schema mutation, authentication, multi-tenancy, LLM orchestration, prompt handling, server-side UI rendering, unregistered catalogs, background jobs, application-data caching, and production exposure of the unauthenticated HTTP listener. The fixed, signed actions described below are the only write boundary.

## Operational checks

Static validation is scoped directly to the source package:

```powershell
uv sync
uv run pytest
uv run ruff format --check src/supabase_mcp
uv run ruff check .
uv run mypy
uv run python -c "from supabase_mcp.config import Settings; print('import ok')"
```

The offline tests use FastMCP's in-memory client and an empty deny-all allowlist, so they exercise real `resources/list`, `resources/read`, `tools/list`, and `tools/call` serialization without Supabase credentials. They also build a wheel and verify the packaged JSON template. A server startup check with a non-empty allowlist remains a live integration check because configured objects are validated against PostgreSQL.

## Decisions

- **2026-09-13:** Added four prediction tools backed by an ownership-scoped `PredictionService` and one lifespan-managed typed `InferenceClient`; public inputs remain semantic, requests are identity-free and chronologically normalized, and BM25 discovery advertises each predictive intent separately.

- **2026-09-12:** Split the fifteen financial tools, services, and request models into eight cohesive domain modules, retained the three former import paths as explicit compatibility facades, and kept one explicit duplicate-checked registration tuple.
- **2026-09-09:** Created a constrained read-only FastMCP/Supabase service.
- **2026-09-11:** Documented the repository as the MCP-only implementation present in the tree and removed stale agent/provider, UI, test-suite, SQL-script, and `src/`-layout claims from the documentation and example environment.
- **2026-09-12:** Added mandatory typed demo-user scope, explicit direct/join ownership rules, fail-closed row queries, and ownership-safe chart mapping.
- **2026-09-11:** Aligned Hatchling, imports, documentation, and static analysis with the `src/supabase_mcp` package layout while preserving the `supabase-mcp` entry point.
- **2026-09-11:** Added the demo banking schema (`users`, `accessibility_preferences`, `accounts`, `transactions`, `subscriptions`) with RLS, a dedicated `mcp_reader` role, and `scripts/seed_demo_data.py` for the initial FluidBank orchestrator integration.
- **2026-09-11:** Added compositional A2UI v0.9.1 support for a bounded database overview, including a packaged resource template, SDK-backed validation, reusable response factory, explicit read-only action registry, safe error acknowledgements, protocol tests, and non-A2UI fallbacks.
- **2026-09-12:** Added `transfers` (simulated self-account transfers, trigger-enforced same-user constraint) and the `monthly_cash_flow` view (income/expenses/net per account per month) to represent transfers and cash flow explicitly. `MCP_ALLOWED_TABLES` must include `public.transfers,public.monthly_cash_flow` for either to be reachable through the server - update this on every deployment (including the Horizon instance), not just locally.
- **2026-09-12:** Made the file-based Horizon entrypoint import-safe by removing the internal/external `a2ui` package-name collision (renamed to `a2ui_support`), constrained sdist contents, and added package-import and `fastmcp inspect` regressions that run without runtime secrets.
- **2026-09-12:** Added explicit protocol assertions that both A2UI resources are UTF-8 textual JSON validated by the registered v0.9.1 catalogs, checked every exposed input schema for JSON serialization, and removed startup stack-trace logging.
- **2026-09-12:** Made MCP authoritative for Finance v2 BankingView, added one stable composed financial surface, registered `request_financial_view`, and separated trusted user scope from the five-field client action.
- **2026-09-12:** Extended the canonical Finance v2 `BankingView` schema with the masked `PaymentCard` object (`cards` on `financial-summary`, `card` on `credit-card` and `card-security`) and the bounded credit-term projection (`creditLimit`, `statementBalance`, `cutoffDate`, `annualInterestRate`, `catPercentage`), and back-ported `totalOwnedBalance`, `totalSpent`, and `insight` so the packaged schema, the Agent's Pydantic mirror, and the client's Zod contract are byte-identical again. `get_accounts` and `get_debt_overview` already read `cards` and `credit_card_terms`, so no table, scope, or allowlist change was required.
- **2026-09-12:** Added structured financial error taxonomy, redacted traceback logging and correlation IDs, pre-dispatch financial request validation, fixed Literal-based custom-period validation across all affected models, and applied the documented dispute period filter.
- **2026-09-13:** Pinned the three app-driven handlers in `ALWAYS_VISIBLE` after progressive discovery broke direct host calls in production. FastMCP delegates `tools/call` to unlisted tools, but the hosted deployment proxy resolves calls against the advertised catalog. The handlers stay app-only, so the model cannot discover or invoke them; the reachability guard tests the advertised catalog.
- **2026-09-13:** Replaced the model-facing `tools/list` with FastMCP's native `BM25SearchTransform` (`search_tools` + `call_tool`, at most five results), declared infrastructure, presentation and confirmed-action tools app-only, rewrote the financial descriptions for retrieval, and added query stopword filtering. The orchestrator takes its model-facing tools from `tools/list`, enforces trusted user scope through the proxy envelope, and normalizes unambiguous malformed proxy calls.
- **2026-09-13:** Removed the former generic row and database-readiness tools from registration and source. A fixed app-only `get_user_context` handler now supplies the orchestrator's existing turn context without accepting caller-selected database objects or query clauses. Internal scoped-selection helpers remain available to domain services, charts, and confirmed-action forms and are not MCP tools.
- **2026-09-13:** Made beneficiary transfers a two-sided internal ledger operation. The form now exposes only verified contacts linked to a FluidBank account, the SQL dispatcher atomically debits the sender and credits that account, and `payment_orders.credited_account_id` preserves the actual destination. External contacts fail with a sanitized actionable error instead of returning success after only a debit.

## Documentation maintenance

Update this file whenever source code, configuration, dependencies, public tool contracts, database access, transport behavior, or repository structure changes. Keep `README.md` user-facing, `AGENTS.md` operational, and `.env.example` free of real credentials.

## A2UI forms and explicitly confirmed writes

`a2ui_actions/inputs.json` describes the Expo input subset; `actions.json` owns the input types, counts, context fields and submit labels for budget and savings-goal create/update/load, transfer execution and credit-card payment. `tools/action_forms.py` prepares eight v0.9.1 surfaces using TextField, DateTimeInput (date only), Slider, ChoicePicker and Button. Transfer choices are built at request time from the authenticated user's eligible accounts, verified beneficiaries linked to FluidBank accounts, and own accounts; the cached static resource remains user-neutral. The payment form uses Finance v2 and binds a validated `BankingView` so Expo shows the masked `PaymentCard` and current credit terms before confirmation. The agent can prepare forms, but the model never receives the `a2ui_action` write tool. Only an explicit client submit routes there under the authenticated Supabase subject. A load action reads an owned record by exact name and fills its update form; duplicate names are rejected.

Writes are the product-authorized exception to the original read-only scope. `DatabaseClient.apply_financial_action` is the only new database boundary. It uses optional `MCP_ACTIONS_DATABASE_URL`, a separate `fluidbank_actions` role and fixed `apply_a2ui_action` SQL. The original read pool, exact allowlists, read-only transactions and TLS requirements remain. Write configuration rejects privileged roles and requires `MCP_ACTIONS_SECRET` (at least 32 characters), shared only by the agent and MCP. The agent signs the complete A2UI event plus its verified user ID with HMAC-SHA256, overwriting any supplied proof. MCP verifies this signature before dispatching writes. Horizon authentication remains in place for remote access; the action proof independently prevents forged trustedScope from authorizing writes. Never give either service secret to Expo or the LLM. Replayed exact events remain idempotent through database receipts.

The review/confirmation UI is the visible populated form and its explicit confirmation button. No LLM call writes data. Context validation, exact action/surface/component allowlists, owner predicates and RLS reject other users' rows. The dispatcher can insert or update budgets and savings goals, transfer to one owned account or beneficiary, and pay one owned active credit card. It cannot delete rows or accept SQL or executable JSON. The SQL migrations add a receipt keyed by user and event identity: the same event is idempotent, concurrent retries serialize, mismatched payloads conflict, and receipt plus mutation commit atomically. Network failures are reported as unconfirmed, not successful. New events after restarting the app are new operations; receipts do not deduplicate independently created forms.

`data.actionResult` is an application transport result (success/failure, safe message, optional code), not a new A2UI protocol message. The Expo UI renders it and retains the form on failure. `a2ui://actions/inputs`, `a2ui://actions/registry` and each action template are discoverable MCP resources. `a2ui_form` only prepares forms. Forms use explicit event.context; sendDataModel stays false to avoid sending unrelated surface data.
