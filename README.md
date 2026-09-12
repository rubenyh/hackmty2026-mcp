# Supabase Read-Only MCP Server

A small FastMCP service that exposes an explicitly allowlisted subset of Supabase PostgreSQL through four read-only tools. It supports stdio for local MCP clients and Streamable HTTP for separately managed clients.

This repository currently contains the MCP server only. It does not contain an LLM agent, chat UI, application API, migrations, or write tools.

## What it protects

- A dedicated PostgreSQL login owns the database connection; do not use the Supabase `postgres` role or a service-role API key.
- `MCP_ALLOWED_TABLES` is an exact allowlist of tables and views. An empty value is deny-all.
- Tables and columns are resolved from reflected metadata; clients cannot submit SQL.
- Values are bound by SQLAlchemy, reads are bounded, and each database transaction is read-only with a local statement timeout.
- TLS is enforced when `sslmode` is omitted and only `require`, `verify-ca`, or `verify-full` are accepted when it is supplied.
- PostgreSQL grants do not bypass Row Level Security. Configure suitable RLS policies for the reader role.

## Prerequisites

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/)
- A Supabase direct or session-pooler PostgreSQL URL for a dedicated read-only role
- Node.js only if you use MCP Inspector

## Configure

Install the project and its locked dependencies, then create a local environment file:

```powershell
uv sync
Copy-Item .env.example .env
```

```bash
uv sync
cp .env.example .env
```

Set the database URL and exact object allowlist in `.env`:

```env
SUPABASE_DATABASE_URL=postgresql://mcp_reader:REPLACE_WITH_PASSWORD@db.PROJECT_REF.supabase.co:5432/postgres?sslmode=require
MCP_ALLOWED_SCHEMAS=public
MCP_ALLOWED_TABLES=public.customers,public.accounts,public.transactions
```

For the Supabase session pooler, use its connection parameters. Both `postgresql://` and `postgresql+psycopg://` are accepted. Percent-encode special characters in usernames and passwords.

All supported settings and defaults are documented in [`.env.example`](.env.example). The service has no `LLM_*`, `OPENAI_*`, or `AGENT_*` settings.

## Run

Stdio (the default):

```powershell
uv run supabase-mcp
# equivalent:
uv run python -m supabase_mcp.server
```

MCP Inspector:

```powershell
npx -y @modelcontextprotocol/inspector uv run python -m supabase_mcp.server
```

Streamable HTTP:

```powershell
$env:MCP_TRANSPORT = "http"
uv run supabase-mcp
```

By default the HTTP MCP endpoint is `http://127.0.0.1:8000/mcp`. The loopback endpoint has no application authentication; exposing it beyond a trusted local environment requires authentication, TLS termination, network controls, rate limiting, secret management, and monitoring.

On Windows, start the module as shown above. `supabase_mcp.server` selects the event-loop policy Psycopg async requires before importing the database stack.

## Tools

- `health_check`: runs a sanitized `SELECT 1` readiness check.
- `list_allowed_tables`: lists configured objects that were successfully reflected at startup.
- `describe_table`: returns cached column metadata for one allowlisted table or view.
- `select_rows`: reads selected columns with typed filters, ordering, limit, and offset.

`select_rows` supports `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `like`, `ilike`, and `is_null`. Filter values are JSON scalars; `in` accepts a non-empty list of at most 100 scalars. The response includes `row_count`, the effective `limit`, `offset`, and a `truncated` flag. If no ordering is supplied, tables with primary keys are ordered by those keys.

## Validate changes

These checks do not require a live database:

```powershell
uv run ruff format --check supabase_mcp
uv run ruff check supabase_mcp
uv run mypy
uv run python -c "from supabase_mcp.config import Settings; print('import ok')"
```

Server configuration always requires a syntactically valid database URL. Startup connects to Supabase when `MCP_ALLOWED_TABLES` is non-empty so every allowlisted object can be validated and reflected; `health_check` also performs a live database round trip.

## Troubleshooting

- **Configuration fails:** confirm the URL is PostgreSQL, identifiers contain only supported PostgreSQL identifier characters, every qualified table uses an allowed schema, and the default limit does not exceed the maximum.
- **Startup fails:** verify connectivity, TLS, the allowlisted object names, schema `USAGE`, and object `SELECT` privileges.
- **Pooler login fails:** copy the session-pooler host, port, database, and username exactly from Supabase; the username commonly includes the project reference.
- **An object is rejected:** add it explicitly to `MCP_ALLOWED_TABLES`. Adding a schema alone does not expose its objects.
- **HTTP is unreachable:** confirm `MCP_TRANSPORT=http`, then check `MCP_HOST`, `MCP_PORT`, and the `/mcp` path.

See [ARCHITECTURE.md](ARCHITECTURE.md) for implementation details and [AGENTS.md](AGENTS.md) for repository contribution rules.
