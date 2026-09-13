# Supabase Read-Only MCP Server

A small FastMCP service that exposes an explicitly allowlisted subset of Supabase PostgreSQL through read-only tools. It supports stdio for local MCP clients and Streamable HTTP for separately managed clients. Selected results can also be presented as declarative [A2UI](https://a2ui.org/) interfaces.

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
MCP_ALLOWED_TABLES=public.users,public.accessibility_preferences,public.accounts,public.transactions,public.subscriptions,public.transfers,public.monthly_cash_flow
```

For the Supabase session pooler, use its connection parameters. Both `postgresql://` and `postgresql+psycopg://` are accepted. Percent-encode special characters in usernames and passwords.

The direct `db.PROJECT_REF.supabase.co` host is IPv6-only and fails to resolve on IPv4-only
networks (`failed to resolve host`). If that happens, switch to the session pooler instead,
with the project ref appended to the username:

```env
SUPABASE_DATABASE_URL=postgresql+psycopg://mcp_reader.PROJECT_REF:REPLACE_WITH_PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres?sslmode=require
```

## Demo data

`scripts/seed_demo_data.py` seeds the demo banking schema (`users`, `accessibility_preferences`,
`accounts`, `transactions`, `subscriptions`, `transfers`) for local development. It writes through the
Supabase service-role key (bypassing RLS) and is safe to re-run — every row uses a UUID
derived deterministically from a stable slug, so re-seeding upserts instead of duplicating:

```bash
pip install -e ".[seed]"
python scripts/seed_demo_data.py
```

It reads `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from `.env`; the MCP server itself never
reads these two variables.

`transfers` (simulated, self-account only) and the `monthly_cash_flow` view (income/expenses/net
per account per month, built on `transactions`) both need to be in `MCP_ALLOWED_TABLES` to be
reachable through the server:

```env
MCP_ALLOWED_TABLES=public.users,public.accessibility_preferences,public.accounts,public.transactions,public.subscriptions,public.transfers,public.monthly_cash_flow
```

All supported settings and defaults are documented in [`.env.example`](.env.example). The service has no `LLM_*`, `OPENAI_*`, or `AGENT_*` settings.

## Run

Stdio (the default):

```powershell
uv run supabase-mcp
# equivalent:
uv run python -m supabase_mcp.server
```

MCP Inspector:

```bash
uv run fastmcp dev inspector src/supabase_mcp/server.py:mcp --project .
```

Streamable HTTP:

```powershell
$env:MCP_TRANSPORT = "http"
uv run supabase-mcp
```

By default the HTTP MCP endpoint is `http://127.0.0.1:8000/mcp`. The loopback endpoint has no application authentication; exposing it beyond a trusted local environment requires authentication, TLS termination, network controls, rate limiting, secret management, and monitoring.

On Windows, start the module as shown above. `supabase_mcp.server` selects the event-loop policy Psycopg async requires before importing the database stack.

## Deploy to Prefect Horizon

Configure Horizon with these exact build settings:

- **Project root:** the repository root containing this `pyproject.toml`. If this directory is checked out as `mcp/` inside a larger monorepo, select `mcp/` as the project root.
- **Python:** `3.12`.
- **Dependencies / requirements:** `pyproject.toml`.
- **Entrypoint:** `src/supabase_mcp/server.py:mcp`.

The `:mcp` suffix is required: Horizon imports the module-level `FastMCP` object and does not execute `main()` or depend on the local stdio transport. The package uses a Hatchling `src` layout and is installed during the build, so no manual `PYTHONPATH` is needed.

Configure runtime values in Horizon's environment/secrets UI, never in a committed `.env`:

- **Required secret:** `SUPABASE_DATABASE_URL`, using a dedicated read-only PostgreSQL role and TLS.
- **Required for data exposure:** `MCP_ALLOWED_TABLES`, containing the exact qualified tables/views. Empty or omitted remains deny-all.
- **Recommended explicit setting:** `MCP_ALLOWED_SCHEMAS` (defaults to `public`).
- **Optional controls:** `MCP_DEFAULT_LIMIT`, `MCP_MAX_LIMIT`, `MCP_STATEMENT_TIMEOUT_MS`, and `LOG_LEVEL`.

`MCP_TRANSPORT`, `MCP_HOST`, and `MCP_PORT` are only used by direct execution through `main()`; Horizon owns its hosted transport when it imports `mcp`.

Before deploying, reproduce Horizon's build/import path from the repository root:

```bash
uv sync --locked
uv build
uv run python -c "from supabase_mcp.server import mcp; print(type(mcp))"
uv run fastmcp inspect src/supabase_mcp/server.py:mcp
```

Importing or inspecting the object does not load `Settings`, start a transport, construct a database engine, or connect to Supabase. Runtime settings and database reflection begin only when FastMCP enters `app_lifespan`.

## Tools

- `health_check`: runs a sanitized `SELECT 1` readiness check.
- `list_allowed_tables`: lists configured objects that were successfully reflected at startup.
- `describe_table`: returns cached column metadata for one allowlisted table or view.
- `select_rows`: reads selected columns with a mandatory typed demo-user scope plus typed filters, ordering, limit, and offset.
- `database_overview`: returns a bounded database-object overview with A2UI v0.9.1 presentation metadata, a dynamic data-model update, structured domain data, and a text fallback.
- `visualize_allowed_data`: reads only selected columns from one reflected allowlisted object and maps them to a bounded area chart (up to 240 rows and four numeric series) or calendar heatmap (up to 500 rows).
- `present_financial_view`: validates one semantic `BankingView` against the authoritative Finance v2 schema and returns the stable composed financial surface.
- `a2ui_action`: dispatches the five A2UI action fields through an explicit read-only allowlist, with trusted application scope carried separately. It supports bounded overview refresh and financial-view requests.
- `a2ui_error`: safely acknowledges client rendering and validation reports without echoing their potentially sensitive message.

`select_rows` and `visualize_allowed_data` require `scope: {"user_id": "<seeded-demo-uuid>"}`. The scope is separate from caller-selected filters and is always combined with them using `AND`. `users`, `accessibility_preferences`, `accounts`, `subscriptions`, and `transfers` use direct ownership; `transactions` and `monthly_cash_flow` use an `EXISTS` relationship through `accounts`. Unknown demo users and allowlisted objects without a configured ownership rule fail closed. Ownership columns cannot be supplied as ordinary filters, and chart mappings cannot use them as visual data.

`select_rows` supports `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `like`, `ilike`, and `is_null`. Filter values are JSON scalars; `in` accepts a non-empty list of at most 100 scalars. The response includes `row_count`, the effective `limit`, `offset`, and a `truncated` flag. If no ordering is supplied, tables with primary keys are ordered by those keys.

## A2UI v0.9.1 over MCP

A2UI is a declarative presentation protocol. It does not replace MCP, FastMCP, the database service, or PostgreSQL permissions. This server implements the current production protocol version `v0.9.1` with MIME type `application/a2ui+json`; it does not use the candidate v1.0 protocol and does not run client-provided code.

All visual surfaces separate cacheable presentation from changing data. `database_overview` remains on the official Basic Catalog at `a2ui://database/overview`. `visualize_allowed_data` uses `a2ui://finance/data-chart` and the project-owned catalog `https://fluidbank.app/a2ui/catalogs/finance/v1`, which contains only `Text`, `Button`, `Card`, `Column`, and `Chart`. `present_financial_view` uses `a2ui://finance/view` and `https://fluidbank.app/a2ui/catalogs/finance/v2`, adding only the semantic `BankingView` component.

The database overview flow is:

1. `resources/list` advertises `a2ui://database/overview`.
2. `resources/read` returns its static `createSurface` and `updateComponents` messages. The template contains data bindings but no Supabase results.
3. `tools/call` for `database_overview` obtains a bounded domain result and returns:
   - useful `TextContent` for clients without A2UI;
   - the same domain result in `structuredContent`;
   - an `EmbeddedResource` containing only `updateDataModel`;
   - `_meta.ui` linking the result to `a2ui://database/overview`.
4. An A2UI-capable client fetches and caches the template, applies the dynamic update, and renders the component tree using its own widgets.

The chart resource follows the same flow. Its packaged `data_chart.json` contains only `createSurface` and `updateComponents`; the tool embeds only `updateDataModel`. The strict request selects a canonical demo-user scope, reflected source, business filters, ordering, limit, and either `{kind: "area", x_column, y_columns}` or `{kind: "heatmap", date_column, value_column}`. It cannot select a component, catalog, URI, style, JSX, or raw A2UI. Numeric columns are checked from reflected metadata, values must be finite, ordering is deterministic, and rows with null required values are omitted and counted. Duplicate mapped labels/dates and malformed dates fail safely.

This scope is hackathon-MVP application filtering. It does not add RLS, JWT verification, Supabase Auth enforcement, or a production authorization boundary; the MCP database role can still read all rows.

`Chart` binds one whole discriminated value at `/chart`: `{kind: "area", accessibleSummary?, props: AreaChartProps}` or `{kind: "heatmap", accessibleSummary?, props: HeatmapChartProps}`. Area series require stable unique IDs; both variants reject unknown properties and bound all arrays and strings. Empty arrays are valid and delegate to the existing client empty states.

### Finance v2 contract

The canonical `BankingView` schema is checked in at `src/supabase_mcp/a2ui_support/catalogs/banking_view.schema.json`. Finance v2 is assembled deterministically from the Finance v1 catalog plus that schema and supports exactly `Text`, `Button`, `Card`, `Column`, `Chart`, and `BankingView`. It keeps A2UI `v0.9.1` and `application/a2ui+json` unchanged. The schema is semantic: it contains the 13 financial intents and their bounded intent-specific data, including the shared empty-state variant, but no arbitrary color, type, spacing, radius, or shadow fields. Card-shaped intents carry a masked `PaymentCard` object (`cards` on `financial-summary`, `card` on `credit-card` and `card-security`) plus the bounded credit terms `creditLimit`, `statementBalance`, `cutoffDate`, `annualInterestRate`, and `catPercentage`; a full card number, CVV or expiry day has no property to travel in.

After interpreting MCP data, the Agent constructs Finance v2 messages against this contract. `present_financial_view` is an optional generic validation/resource factory for MCP callers, not the owner of intent selection or data retrieval. Its request fields are `request.view`, `request.actionLabel`, and `request.requestIntent`, and `view` must satisfy the canonical schema. The stable surface is `financial-view`; its flat component array has `root`, `banking_view`, `request_financial_view_label`, and `request_financial_view_button`. The root `Column` references the BankingView and button; the button references the label and emits `request_financial_view` with `context.intent` bound to `/requestIntent`. These IDs and bindings are contract values and must not be generated per response.

The client action remains the five-field object `name`, `surfaceId`, `sourceComponentId`, `timestamp`, and `context`. When forwarding it to `a2ui_action`, trusted application scope is supplied separately as `trustedScope: {"user_id": "<authenticated-supabase-uuid>"}`. For `request_financial_view`, context requires one of the 13 Finance v2 intents and may contain only `accountId`, `startDate`, `endDate`, and `period`. Identity fields such as `user_id` and `email` are rejected from client context. The normalized result keeps `action`, `request`, and `trustedScope` as separate objects so the Agent can re-enter intent interpretation and retrieval without MCP choosing a chart.

The embedded resource is annotated for the `user` audience so a supporting host can render it without putting presentation JSON into the model context. The separate fallback and structured domain data remain available for reasoning and for clients that ignore embedded resources.

### Inspect the protocol

Start Inspector from this directory:

```bash
uv run fastmcp dev inspector src/supabase_mcp/server.py:mcp --project .
```

In Inspector:

1. List resources and read `a2ui://database/overview`.
2. List tools and inspect `database_overview`; its definition includes `_meta.ui`.
3. Call it with `{"limit": 25}` and inspect its text, `structuredContent`, embedded `updateDataModel`, and runtime `_meta.ui`.
4. Optionally call `a2ui_action` with `name`, `surfaceId`, `sourceComponentId`, `timestamp`, and `context` as emitted by the refresh button.

Inspector exposes the real MCP JSON but does not render A2UI. A rendering client must recognize `application/a2ui+json`, resolve `_meta.ui.resourceUri`, validate/process v0.9.1 messages, implement the declared allowlisted catalog, maintain per-surface data state, and forward component actions to `a2ui_action`.

### Extend A2UI safely

To add a surface:

1. Add a static JSON template under `src/supabase_mcp/a2ui_support/templates/` using `v0.9.1`, one registered catalog, stable component IDs, a `root`, valid component references, and data bindings.
2. Add a `SurfaceSpec` and register it in `a2ui_support/surfaces.py`; registration loads it through `importlib.resources`, rejects duplicate IDs/URIs or missing templates, and validates it with the official SDK.
3. Publish the cached template with `mcp.resource(...)` and its stable `a2ui://` URI.
4. Write a pure mapper from the domain result to the template data model, then use `A2UIResponseFactory` in only the tool that needs that surface.

To add a custom component, first extend the versioned catalog, validate it with the installed SDK, synchronize the checked-in agent copy, implement an explicit client adapter, and add shared accept/reject fixtures plus package-content tests. Do not expose renderers, error boundaries, low-level drawing primitives, callbacks, styles, or generic objects. To add an action, include it on a template component, define a strict Pydantic context model, and add one fixed `RegisteredAction` to the central registry. Do not create a tool per button or derive handlers with `eval`, dynamic imports, or input-driven `getattr`.

### Catalog negotiation limitation

A2UI recommends negotiating supported catalogs during MCP `initialize`. FastMCP 4.0.3 does not expose a documented public server hook for reading arbitrary client initialization capabilities and persisting a selected custom catalog per session. This implementation therefore does not claim initialize-time negotiation, does not use FastMCP internals or monkeypatching, and emits only its fixed allowlist: the official Basic Catalog and Finance Catalogs v1 and v2. A controlled client must recognize the catalog declared by each surface; unsupported clients continue to use the text and structured-data fallback. Per-call capability metadata is not consumed because FastMCP does not expose it to these typed handlers as a stable catalog-negotiation API.

## Validate changes

These checks do not require a live database:

```powershell
uv run pytest
uv run ruff format --check src/supabase_mcp
uv run ruff check .
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

## Forms and saving budgets/goals

The mobile repository includes `supabase/migrations/202609130001_a2ui_actions.sql` (run after the financial question-bank schema). Apply it, set a password for the dedicated `fluidbank_actions` PostgreSQL login through your administrator, and configure its TLS connection as `MCP_ACTIONS_DATABASE_URL`. Never substitute postgres or service_role. Keep budgets and savings_goals in MCP_ALLOWED_TABLES and keep the original read connection. Set the same random `MCP_ACTIONS_SECRET` (at least 32 characters) on agent and MCP. The agent signs the complete event plus verified user ID; the MCP verifies the HMAC before any write. This works over the existing Horizon remote transport. Missing or mismatched signatures fail closed. No migration or deployment is performed merely by changing this code.

`a2ui_form` prepares forms; `a2ui_action` can now save user-confirmed budgets and goals. Missing write configuration returns `writes_not_configured`, with no simulated success. `a2ui_actions/actions.json` declares six actions and each required input. Synchronize copies/templates from the mobile workspace using `node scripts/sync-a2ui-actions.mjs`; CI can use `--check`.
