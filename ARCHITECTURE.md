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
    models.py         Strict tool inputs and structured results
    serialization.py  PostgreSQL-to-JSON-safe conversion
    server.py         Event-loop setup, FastMCP lifespan, registration, and entry point
    services/
      database_overview.py  Bounded presentation-independent overview use case
    a2ui/
      constants.py    v0.9.1, MIME, catalog, action, and stable URI identifiers
      models.py       Immutable SurfaceSpec
      validation.py   Official SDK validation plus local surface invariants
      surfaces.py     Central validated surface/template registry and cache
      response.py     Reusable ToolResult/updateDataModel composition
      mappers.py      Pure domain-to-data-model and fallback mappings
      actions.py      Typed action context and explicit handler allowlist
      templates/
        database_overview.json  Static createSurface/updateComponents messages
    tools/
      a2ui.py         Overview, generic action/error, and resource handlers
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

FastMCP's lifespan creates one shared `DatabaseClient`, starts it before serving requests, makes it available through the tool context, and disposes it during shutdown. The module preserves the four original tools (`health_check`, `list_allowed_tables`, `describe_table`, and `select_rows`) and adds `database_overview`, `a2ui_action`, and `a2ui_error`. It also publishes the database-overview presentation template as a read-only resource.

`main()` selects stdio unless `MCP_TRANSPORT=http`. HTTP uses the configured host and port; FastMCP exposes its MCP endpoint at `/mcp`. The service itself adds no authentication, authorization middleware, reverse-proxy TLS, rate limiting, or tenant isolation.

## Database lifecycle and least privilege

`DatabaseClient` owns one SQLAlchemy async engine with a small bounded pool (`pool_size=3`, `max_overflow=2`, five-second pool timeout, and connection pre-ping). On startup it reflects only exact allowlisted tables and views. A non-empty allowlist fails startup if an object is missing, inaccessible, or cannot be reflected. An empty allowlist performs no reflection and exposes no row-selection surface.

Every database operation opens a transaction and executes:

1. `SET TRANSACTION READ ONLY`.
2. A transaction-local PostgreSQL `statement_timeout` through `set_config`.
3. The health or selection statement.

These application controls complement, rather than replace, database controls. Deployments must use a dedicated login with only `CONNECT`, schema `USAGE`, explicit `SELECT`, and suitable Row Level Security policies. The role must not own protected tables, have `BYPASSRLS`, or use Supabase administrative/service-role credentials.

## Query construction

Clients cannot provide SQL. A `SelectRequest` names a reflected schema/object, optional reflected columns, typed filters, typed ordering, an optional limit, and a non-negative offset. Pydantic models forbid unknown fields.

Supported filter operators are `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `like`, `ilike`, and `is_null`. Ordinary operators require a JSON scalar; `is_null` requires a boolean; `in` requires a non-empty list of at most 100 JSON scalars. SQLAlchemy builds bound expressions for values.

The effective limit is the request limit or `MCP_DEFAULT_LIMIT` and cannot exceed `MCP_MAX_LIMIT`. The query fetches one additional row to set `truncated`, then returns at most the effective limit. Explicit ordering is applied in request order; otherwise primary-key columns provide deterministic ordering when present.

## Tool contracts and errors

- `health_check` returns readiness and database availability without database error details.
- `list_allowed_tables` returns only successfully reflected allowlisted tables/views and a count.
- `describe_table` returns cached names, SQL types, nullability, and primary-key flags.
- `select_rows` returns JSON-safe rows, count, effective pagination values, and truncation state.

Known request failures use stable public codes such as `object_not_allowed`, `column_not_allowed`, `limit_exceeded`, and `invalid_request`. Unexpected failures are reduced to sanitized `server_error`, `database_error`, or `database_unavailable` results. Logs record an operation label and exception class, not credentials or row bodies.

Serialization preserves primitive JSON values, stringifies UUIDs and decimals, emits ISO-8601 date/time strings, converts enums through their values, Base64-encodes bytes, and recursively handles mappings and sequences. Unknown values fall back to strings.

## A2UI presentation boundary

A2UI is an optional presentation layer over MCP, not a database or authorization layer. Only `database_overview` currently uses it. Normal MCP tools continue returning their existing typed results without inheriting from an A2UI base class.

`SurfaceRegistry` owns the stable mapping from surface ID to resource URI and packaged JSON template. Registration loads templates with `importlib.resources`, rejects duplicate surface IDs and resource URIs, rejects missing or malformed templates, checks the `v0.9.1` version and `v0_9_1` Basic Catalog identifier, verifies the surface ID, ordering, unique component IDs, and `root`, and runs the official `a2ui-agent-sdk` validator. The validated serialized template is cached and served at `a2ui://database/overview` without consulting PostgreSQL.

`database_overview` calls a bounded domain service over `DatabaseClient.list_allowed_objects()`. The domain result has no A2UI dependency. A pure mapper produces a small data model for the template. `A2UIResponseFactory` converts it to a validated `updateDataModel` with `path: "/"`, adds a text fallback, preserves a detached JSON-safe domain result in `structuredContent`, embeds the A2UI update using `application/a2ui+json` and `Annotations(audience=["user"])`, and adds the same `_meta.ui` resource link used in the static tool definition. It can also update a validated absolute JSON Pointer without rebuilding the layout.

The static template contains only `createSurface` and `updateComponents`. It binds text and action context to the dynamic model and contains no database values. The dynamic tool response contains only `updateDataModel`; clients may cache the static template independently.

## A2UI actions and errors

There is one generic `a2ui_action` tool with the five protocol fields `name`, `surfaceId`, `sourceComponentId`, `timestamp`, and `context`. `ActionRegistry` maps a fixed name to a fixed handler and strict Pydantic context model. Registration verifies that the action and source component occur in the registered template. Dispatch verifies the timestamp, surface, component, and context before calling the handler. It never uses `eval`, dynamic imports, or input-driven attribute lookup. The only registered action, `refresh_database_overview`, reuses the read-only overview domain service and is bounded to 100 objects.

The generic `a2ui_error` handler recognizes `VALIDATION_FAILED`, returns a safe acknowledgement, and logs only bounded structural metadata: whether the error is a validation failure, whether the surface is known, path presence, and message length. It does not log or echo the client-provided code, message, path, stack trace, rows, or credentials.

## Catalog support and negotiation

The server supports exactly A2UI `v0.9.1` with `https://a2ui.org/specification/v0_9_1/catalogs/basic/catalog.json`; inline and arbitrary catalogs are not accepted. `a2ui-agent-sdk` 0.5.x supplies the bundled schema and catalog validator. Local validation supplements, rather than replaces, that SDK only for application-level consistency such as the registered surface and exact catalog URI.

A2UI recommends selecting catalogs from custom client capabilities during MCP `initialize`. Inspection of FastMCP 4.0.3's documented public server APIs found no stable hook that exposes arbitrary initialization capabilities to these typed handlers with session-scoped storage. The server therefore does not implement or claim initialize-time catalog negotiation and does not depend on FastMCP internals or monkeypatches. Controlled clients may advertise and recognize the fixed catalog; all other clients retain the text and `structuredContent` fallback. Per-call A2UI capability metadata is likewise not used as a substitute for a verified session negotiation API.

## Security boundary and non-goals

The safety model is layered:

- PostgreSQL role grants and RLS define the authoritative data permissions.
- Configuration narrows exposure to named schemas and objects.
- Reflection narrows selectable identifiers to known columns.
- Typed inputs and SQLAlchemy binding prevent arbitrary statements and value interpolation.
- Read-only transactions, timeouts, pooling bounds, and row limits constrain execution.
- Structured results and sanitized errors constrain the MCP boundary.

Explicit non-goals are writes, arbitrary SQL, schema mutation, authentication, multi-tenancy, LLM orchestration, prompt handling, server-side UI rendering, arbitrary/custom catalogs, background jobs, application-data caching, and production exposure of the unauthenticated HTTP listener.

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

- **2026-09-09:** Created a constrained read-only FastMCP/Supabase service.
- **2026-09-11:** Documented the repository as the MCP-only implementation present in the tree and removed stale agent/provider, UI, test-suite, SQL-script, and `src/`-layout claims from the documentation and example environment.
- **2026-09-11:** Aligned Hatchling, imports, documentation, and static analysis with the `src/supabase_mcp` package layout while preserving the `supabase-mcp` entry point.
- **2026-09-11:** Added the demo banking schema (`users`, `accessibility_preferences`, `accounts`, `transactions`, `subscriptions`) with RLS, a dedicated `mcp_reader` role, and `scripts/seed_demo_data.py` for the initial FluidBank orchestrator integration.
- **2026-09-11:** Added compositional A2UI v0.9.1 support for a bounded database overview, including a packaged resource template, SDK-backed validation, reusable response factory, explicit read-only action registry, safe error acknowledgements, protocol tests, and non-A2UI fallbacks.
- **2026-09-12:** Added `transfers` (simulated self-account transfers, trigger-enforced same-user constraint) and the `monthly_cash_flow` view (income/expenses/net per account per month) to represent transfers and cash flow explicitly. `MCP_ALLOWED_TABLES` must include `public.transfers,public.monthly_cash_flow` for either to be reachable through the server - update this on every deployment (including the Horizon instance), not just locally.

## Documentation maintenance

Update this file whenever source code, configuration, dependencies, public tool contracts, database access, transport behavior, or repository structure changes. Keep `README.md` user-facing, `AGENTS.md` operational, and `.env.example` free of real credentials.
