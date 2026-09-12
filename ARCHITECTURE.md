# Architecture

## Scope

The repository currently implements a standalone read-only Model Context Protocol server over Supabase PostgreSQL. It exposes a deliberately small, typed query surface to MCP clients. It does not include an LLM agent, an OpenAI/Gemini integration, a user interface, application authentication, migrations, arbitrary SQL, or database writes.

```text
MCP client
    -> FastMCP transport and tool registry
    -> typed tool handler
    -> DatabaseClient
    -> SQLAlchemy async engine / Psycopg
    -> Supabase PostgreSQL
```

The server supports stdio and Streamable HTTP. Stdio is the default and is suitable for a client-managed local subprocess. HTTP listens on loopback by default and is not production-secure by itself.

## Repository map

```text
supabase_mcp/
  __init__.py       Package marker
  config.py         Environment parsing, normalization, and validation
  database.py       Engine lifecycle, reflection, query construction, and execution
  errors.py         Internal safe error types
  models.py         Strict tool inputs and structured results
  serialization.py  PostgreSQL-to-JSON-safe conversion
  server.py         Event-loop setup, FastMCP lifespan, registration, and entry point
  tools/
    health.py       Sanitized database readiness check
    schema.py       Allowlisted object discovery and description
    select.py       Structured bounded selection
.env.example        Placeholder-only server configuration
README.md           Operator and client-facing usage
AGENTS.md           Coding-agent contribution rules
pyproject.toml      Dependency and tool configuration
Dockerfile          Container definition
uv.lock             Locked dependency graph
```

No `src/`, `app_agent/`, `tests/`, or `sql/` directory is present in the current repository tree. Hatch packages the root-level `supabase_mcp/` directory, and the installed `supabase-mcp` command calls `supabase_mcp.server:main`.

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

FastMCP's lifespan creates one shared `DatabaseClient`, starts it before serving requests, makes it available through the tool context, and disposes it during shutdown. The module registers exactly four tools: `health_check`, `list_allowed_tables`, `describe_table`, and `select_rows`.

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

## Security boundary and non-goals

The safety model is layered:

- PostgreSQL role grants and RLS define the authoritative data permissions.
- Configuration narrows exposure to named schemas and objects.
- Reflection narrows selectable identifiers to known columns.
- Typed inputs and SQLAlchemy binding prevent arbitrary statements and value interpolation.
- Read-only transactions, timeouts, pooling bounds, and row limits constrain execution.
- Structured results and sanitized errors constrain the MCP boundary.

Explicit non-goals are writes, arbitrary SQL, schema mutation, authentication, multi-tenancy, LLM orchestration, prompt handling, UI generation, background jobs, caching, and production exposure of the unauthenticated HTTP listener.

## Operational checks

Static validation is scoped directly to the root package:

```powershell
uv sync
uv run ruff format --check supabase_mcp
uv run ruff check supabase_mcp
uv run mypy
uv run python -c "from supabase_mcp.config import Settings; print('import ok')"
```

A server startup check is an integration check because a non-empty allowlist is validated against the configured live database.

## Decisions

- **2026-09-09:** Created a constrained read-only FastMCP/Supabase service.
- **2026-09-11:** Documented the repository as the MCP-only implementation present in the tree and removed stale agent/provider, UI, test-suite, SQL-script, and `src/`-layout claims from the documentation and example environment.
- **2026-09-11:** Aligned project metadata with the root-level MCP package, removed the obsolete agent dependency and console entry point, and scoped static analysis to `supabase_mcp`.

## Documentation maintenance

Update this file whenever source code, configuration, dependencies, public tool contracts, database access, transport behavior, or repository structure changes. Keep `README.md` user-facing, `AGENTS.md` operational, and `.env.example` free of real credentials.
