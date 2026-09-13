# Architecture

## Scope

The repository currently implements a standalone read-only Model Context Protocol server over Supabase PostgreSQL. It exposes a deliberately small, typed query surface to MCP clients and a reusable A2UI v0.9.1 presentation layer for selected results. It does not include an LLM agent, an OpenAI/Gemini integration, a renderer, application authentication, migrations, arbitrary SQL, or database writes.

```text
MCP client
    -> FastMCP transport
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
```

The server supports stdio and Streamable HTTP. Stdio is the default and is suitable for a client-managed local subprocess. HTTP listens on loopback by default and is not production-secure by itself.

## Repository map

```text
src/
  supabase_mcp/
    __init__.py       Package marker
    config.py         Environment parsing, normalization, and validation
    database.py       Engine lifecycle, reflection, query construction, and execution
    errors.py         Internal safe error types
    models.py         Strict generic tool inputs and structured results
    finance_models/   Strict financial contracts grouped by domain
    serialization.py  PostgreSQL-to-JSON-safe conversion
    server.py         Event-loop setup, FastMCP lifespan, registration, and entry point
    services/
      database_overview.py  Bounded presentation-independent overview use case
      finance/        Financial rules and coordinated reads grouped by domain
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
      a2ui.py         Overview, generic action/error, and resource handlers
      finance/        Thin financial MCP handlers and explicit registration tuple
      health.py       Sanitized database readiness check
      schema.py       Allowlisted object discovery and description
      select.py       Structured bounded selection
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

`transfers` represents a simulated (never real) money movement between two accounts belonging to the *same* user. A `before insert or update` trigger (`enforce_transfer_same_user`, fixed `search_path`) rejects any row where the two accounts don't both belong to `transfers.user_id` - cross-user transfers are rejected at the database level, not just by application logic. Every seeded transfer has `status = 'simulated'` and never touches `accounts.available_balance` or writes to `transactions`; a hypothetical resulting balance is something a caller computes from the existing account rows, not something this schema materializes. `completed`/`failed` are reserved statuses for a possible future write-capable tool, which - per `AGENTS.md` - does not exist yet and requires its own authorization model and security review before it's added.

`monthly_cash_flow` answers "income vs. expenses" directly: one row per account per calendar month, summing `transactions.amount` by `direction` (`credit` = income, `debit` = expenses) plus a `net` column. It's created `WITH (security_invoker = true)` so it inherits the querying role's RLS instead of the view owner's privileges, and `mcp_reader` has an explicit `GRANT SELECT` on it (views need that in addition to RLS).

The `mcp_reader` Postgres role is a dedicated, `SELECT`-only login (via per-table RLS policies scoped to that role) created directly in Supabase, separate from this repository's tracked migrations. `SUPABASE_DATABASE_URL` uses the session pooler (`aws-0-ca-central-1.pooler.supabase.com:5432`, username `mcp_reader.<project_ref>`) rather than the direct `db.<ref>.supabase.co` host, which is IPv6-only and fails to resolve on IPv4-only networks.

## Configuration boundary

`Settings` uses `pydantic-settings`, reads process environment variables plus a local `.env`, ignores unrelated variables, and validates:

- a required PostgreSQL URL using the `postgres`, `postgresql`, or `postgresql+psycopg` scheme;
- TLS modes `require`, `verify-ca`, or `verify-full` when `sslmode` is supplied;
- one or more allowed schemas and an exact, possibly empty, table/view allowlist;
- PostgreSQL-like identifiers and unique normalized `(schema, object)` pairs;
- positive default and maximum row limits, with a maximum cap of 10,000;
- a statement timeout from 100 through 60,000 milliseconds;
- `stdio` or `http` transport, a non-empty host, a valid TCP port, and an enumerated log level.

Unqualified allowlist entries are accepted only when exactly one schema is configured. `sqlalchemy_url()` normalizes accepted URLs to the async Psycopg dialect and adds `sslmode=require` when absent. The unmasked URL is used only to construct the engine and must never be logged.

## Server lifecycle and transports

`supabase_mcp.server` selects `WindowsSelectorEventLoopPolicy` on Windows before importing FastMCP or database modules. This ordering is required by Psycopg's async implementation.

FastMCP's lifespan creates one shared `DatabaseClient`, starts it before serving requests, makes it available through the tool context, and disposes it during shutdown. The module preserves the four original tools (`health_check`, `list_allowed_tables`, `describe_table`, and `select_rows`) and adds `database_overview`, `visualize_allowed_data`, `present_financial_view`, `chat_message`, `a2ui_action`, and `a2ui_error`. It publishes the corresponding A2UI presentation templates as read-only resources.

`main()` selects stdio unless `MCP_TRANSPORT=http`. HTTP uses the configured host and port; FastMCP exposes its MCP endpoint at `/mcp`. The service itself adds no authentication, authorization middleware, reverse-proxy TLS, rate limiting, or tenant isolation.

Importing `supabase_mcp.server` constructs and registers the module-level `mcp` object but does not call `load_settings()`, create an engine, enter the lifespan, connect to PostgreSQL, or start a transport. This makes package imports and Horizon's file-based inspection safe without build-time secrets. Direct execution remains isolated behind the `if __name__ == "__main__"` guard.

The internal A2UI integration package is named `a2ui_support`, rather than `a2ui`, because FastMCP's file-based loader temporarily places `src/supabase_mcp` on the import path. Reusing the external SDK's top-level name caused `from a2ui...` to resolve to the internal package during `fastmcp inspect`, producing a circular import. The distinct package name keeps file-based and installed-package imports equivalent.

## Packaging and Horizon deployment

Hatchling builds the `src/supabase_mcp` package into the wheel, including both static A2UI templates and the packaged Finance Catalog JSON. Runtime imports use the installed `supabase_mcp` package and do not depend on a manually configured `PYTHONPATH`. Python 3.12 satisfies the declared `>=3.11` requirement. Runtime libraries imported by the package are declared in `[project.dependencies]`; test and build tooling remains in the development dependency group.

The sdist target uses an explicit source allowlist. This prevents local virtual environments, build directories, `.env`, caches, and other untracked workstation files from being copied into release artifacts. Horizon generates its own runtime image from `pyproject.toml`, so the repository `Dockerfile` is not part of this deployment path and remains unchanged.

Horizon must use the repository directory containing `pyproject.toml` as its project root, Python 3.12, `pyproject.toml` as its dependency file, and `src/supabase_mcp/server.py:mcp` as its entrypoint. `SUPABASE_DATABASE_URL` is injected at runtime. `MCP_ALLOWED_TABLES` stays deny-all when empty; deployments that expose data must configure it explicitly, and should explicitly configure `MCP_ALLOWED_SCHEMAS` as well. Horizon owns the hosted transport and does not invoke `main()`.

## Database lifecycle and least privilege

`DatabaseClient` owns one SQLAlchemy async engine with a small bounded pool (`pool_size=3`, `max_overflow=2`, five-second pool timeout, and connection pre-ping). On startup it reflects only exact allowlisted tables and views. A non-empty allowlist fails startup if an object is missing, inaccessible, or cannot be reflected. An empty allowlist performs no reflection and exposes no row-selection surface.

Every database operation opens a transaction and executes:

1. `SET TRANSACTION READ ONLY`.
2. A transaction-local PostgreSQL `statement_timeout` through `set_config`.
3. The health or selection statement.

These application controls complement, rather than replace, database controls. Deployments must use a dedicated login with only `CONNECT`, schema `USAGE`, explicit `SELECT`, and suitable Row Level Security policies. The role must not own protected tables, have `BYPASSRLS`, or use Supabase administrative/service-role credentials.

Startup failures are logged only by bounded operation name and exception class. Exception text and stack traces are intentionally excluded so connection and SQL details cannot escape through platform logs.

## Query construction

Clients cannot provide SQL. A `SelectRequest` names a reflected schema/object, a mandatory typed `UserScope`, optional reflected columns, typed filters, typed ordering, an optional limit, and a non-negative offset. Pydantic models forbid unknown fields.

`TABLE_USER_SCOPES` is the explicit ownership registry. `users.id`, `accessibility_preferences.user_id`, `accounts.user_id`, `subscriptions.user_id`, and `transfers.user_id` are direct scopes. `transactions.account_id` and `monthly_cash_flow.account_id` are scoped with a parameterized correlated `EXISTS` through `accounts.id` and `accounts.user_id`. The canonical scope predicate is added before all business filters, so SQLAlchemy combines them with `AND`. Unknown/non-demo UUIDs, missing ownership metadata, model-style ownership filters, and allowlisted objects without a registry entry fail with sanitized errors instead of returning rows.

Supported filter operators are `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `like`, `ilike`, and `is_null`. Ordinary operators require a JSON scalar; `is_null` requires a boolean; `in` requires a non-empty list of at most 100 JSON scalars. SQLAlchemy builds bound expressions for values.

The effective limit is the request limit or `MCP_DEFAULT_LIMIT` and cannot exceed `MCP_MAX_LIMIT`. The query fetches one additional row to set `truncated`, then returns at most the effective limit. Explicit ordering is applied in request order; otherwise primary-key columns provide deterministic ordering when present.

## Tool contracts and errors

- `health_check` returns readiness and database availability without database error details.
- `list_allowed_tables` returns only successfully reflected allowlisted tables/views and a count.
- `describe_table` returns cached names, SQL types, nullability, and primary-key flags.
- `select_rows` returns JSON-safe rows, count, effective pagination values, and truncation state.

Known request failures use stable public codes such as `object_not_allowed`, `column_not_allowed`, `limit_exceeded`, and `invalid_request`. Unexpected failures are reduced to sanitized `server_error`, `database_error`, or `database_unavailable` results. Logs record an operation label and exception class, not credentials or row bodies.

Visualization query failures raised by the database driver use the actionable, sanitized `database_error` result rather than falling through to a generic server failure. Protocol responses never include driver text, SQL statements, connection details, or stack traces.

Serialization preserves primitive JSON values, stringifies UUIDs and decimals, emits ISO-8601 date/time strings, converts enums through their values, Base64-encodes bytes, and recursively handles mappings and sequences. Unknown values fall back to strings.

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

Explicit non-goals are writes, arbitrary SQL, schema mutation, authentication, multi-tenancy, LLM orchestration, prompt handling, server-side UI rendering, unregistered catalogs, background jobs, application-data caching, and production exposure of the unauthenticated HTTP listener.

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

## Documentation maintenance

Update this file whenever source code, configuration, dependencies, public tool contracts, database access, transport behavior, or repository structure changes. Keep `README.md` user-facing, `AGENTS.md` operational, and `.env.example` free of real credentials.

## A2UI forms and explicitly confirmed writes

`a2ui_actions/inputs.json` describes the Expo input subset; `actions.json` owns the input types, counts, context fields and submit labels for budget and savings-goal create/update/load. `tools/action_forms.py` prepares six Basic v0.9.1 surfaces using native TextField, DateTimeInput (date only), Slider and Button. The agent can prepare forms, but the model never receives the `a2ui_action` write tool. Only an explicit client submit routes there under the authenticated Supabase subject. A load action reads an owned record by exact name and fills its update form; duplicate names are rejected.

Writes are the product-authorized exception to the original read-only scope. `DatabaseClient.apply_financial_action` is the only new database boundary. It uses optional `MCP_ACTIONS_DATABASE_URL`, a separate `fluidbank_actions` role and fixed `apply_a2ui_action` SQL. The original read pool, exact allowlists, read-only transactions and TLS requirements remain. Write configuration rejects privileged roles and requires `MCP_ACTIONS_SECRET` (at least 32 characters), shared only by the agent and MCP. The agent signs the complete A2UI event plus its verified user ID with HMAC-SHA256, overwriting any supplied proof. MCP verifies this signature before dispatching writes. Horizon authentication remains in place for remote access; the action proof independently prevents forged trustedScope from authorizing writes. Never give either service secret to Expo or the LLM. Replayed exact events remain idempotent through database receipts.

The review/confirmation UI is the visible populated form and its explicit Crear/Guardar cambios button. No LLM call writes data. Context validation, exact action/surface/component allowlists, owner predicates and RLS reject other users' rows. Only budgets and savings_goals may be inserted/updated; no transfers, payments, balances, deletion, arbitrary SQL or executable JSON. The separate SQL migration adds a receipt keyed by user and event identity: the same event is idempotent, concurrent retries serialize, mismatched payloads conflict, and receipt plus mutation commit atomically. Network failures are reported as unconfirmed, not successful. New events after restarting the app are new operations; receipts do not deduplicate independently created forms.

`data.actionResult` is an application transport result (success/failure, safe message, optional code), not a new A2UI protocol message. The Expo UI renders it and retains the form on failure. `a2ui://actions/inputs`, `a2ui://actions/registry` and each action template are discoverable MCP resources. `a2ui_form` only prepares forms. Forms use explicit event.context; sendDataModel stays false to avoid sending unrelated surface data.
