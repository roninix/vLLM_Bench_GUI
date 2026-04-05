# CLAUDE.md — vLLM Benchmark GUI (Web)

## Project Overview

A locally-hosted web application for benchmarking vLLM inference servers.
A Python backend (FastAPI) serves the API and a single-page HTML frontend.
The user opens a browser tab at `http://localhost:7843`. No external internet
required at runtime; all CDN assets are vendored on first run.

Core capabilities:
- Manage vLLM server profiles
- Configure and run parametric benchmarks (server, model, concurrency, prompts, …)
- Persist every run in a local SQLite database, per server
- Compare runs historically (single server) and cross-server (any two servers from the address book)
- Render interactive tables and charts
- Export / backup the database and settings on demand

---

## Infrastructure Context (Reference Only — NOT hardcoded)

> **All server addresses, ports, and aliases are user-managed at runtime.**
> Nothing below appears as a default or seed in the code. This section
> documents the target environment for context only.

### Known vLLM Servers (user will add these via the UI)

| Alias      | LAN IP       | Port | Hardware                                         |
|------------|--------------|------|--------------------------------------------------|
| castleai   | 192.168.1.22 | 8018 | ASUS Ascent GX10 — NVIDIA GB10 Grace Blackwell (128 GB unified memory) |
| castleai2  | 192.168.1.32 | 8018 | ASUS Ascent GX10 — NVIDIA GB10 Grace Blackwell (128 GB unified memory) |

Both expose OpenAI-compatible endpoints (`/v1/models`, `/v1/chat/completions`).
Accessible over LAN (192.168.1.x) and Tailscale overlay.

### Dev Machines

| Host          | Role                       | OS            |
|---------------|----------------------------|---------------|
| castlemac     | Primary dev, runs the app  | macOS (M4)    |
| castlejasper  | Secondary dev/test         | Ubuntu 24.04  |

---

## Server Address Book

Servers are **exclusively user-managed**. There are no hardcoded defaults,
no seed data, and no environment variables for server addresses.

### First-run experience

On first launch the database is empty. The app opens directly on the
**Servers** tab with a prominent empty-state prompt:

```
  No servers yet.
  [ + Add your first vLLM server ]
```

### Server record fields

| Field         | Required | Notes                                      |
|---------------|----------|--------------------------------------------|
| `alias`       | ✓        | Short unique name, used in all dropdowns   |
| `host`        | ✓        | IP address or hostname                     |
| `port`        | ✓        | Default 8000 (user must set correct value) |
| `description` |          | Free text, e.g. hardware notes             |
| `color`       |          | Hex colour for chart series (auto-assigned if blank) |
| `tags`        |          | Comma-separated, for filtering             |

The `color` field is auto-assigned from a fixed palette on creation
and can be changed via the edit dialog. It is used consistently across
all charts so the same server always renders in the same colour.

### Server management UI (Servers tab)

```
┌─ SERVERS ────────────────────────────────────────── [+ Add Server] ─┐
│                                                                      │
│  ● my-gpu-server     192.168.1.22:8018   ████  NVIDIA GB10          │
│    2 runs · last run 2025-06-01 14:30    [✎ Edit] [🗑 Delete] [Ping]│
│                                                                      │
│  ● inference-box     192.168.1.32:8018   ████  NVIDIA GB10          │
│    1 run  · last run 2025-06-01 14:45    [✎ Edit] [🗑 Delete] [Ping]│
│                                                                      │
│  ○ dev-laptop        localhost:8000      ████  (unreachable)         │
│    0 runs                                [✎ Edit] [🗑 Delete] [Ping]│
└──────────────────────────────────────────────────────────────────────┘
```

Status dot: green = reachable (last ping OK), grey = not yet pinged,
red = last ping failed. Auto-pinged every 30 s for servers used recently.

### Add / Edit dialog

```
┌─ Add Server ─────────────────────────────────────────────────────────┐
│  Alias        [ my-gpu-server            ]  (unique, no spaces)      │
│  Host         [ 192.168.1.22             ]                           │
│  Port         [ 8018                     ]                           │
│  Description  [ ASUS Ascent GX10 GB10    ]                           │
│  Color        [████] (colour picker)                                 │
│  Tags         [ local, blackwell         ]                           │
│                                                                      │
│  [Test Connection]  →  ✓ Reachable · 2 models · 12ms                │
│                                                                      │
│               [Cancel]  [Save]                                       │
└──────────────────────────────────────────────────────────────────────┘
```

`[Test Connection]` calls `/api/servers/test` (no alias required) with
`{host, port}` so it works before the server is saved.

### Delete guard

If a server has associated benchmark runs, deletion shows a warning:

```
  ⚠ "my-gpu-server" has 7 benchmark runs.
  Deleting it will also delete all associated results.
  [ Cancel ]  [ Delete server + results ]
```

---

## Tech Stack

### Backend

| Package       | Version  | Purpose                                    |
|---------------|----------|--------------------------------------------|
| `fastapi`     | ≥ 0.111  | HTTP API + static file serving             |
| `uvicorn`     | ≥ 0.29   | ASGI server (auto-reload in dev)           |
| `aiohttp`     | ≥ 3.9    | Async HTTP calls to vLLM endpoints         |
| `aiosqlite`   | ≥ 0.20   | Async SQLite driver                        |
| `pydantic`    | v2       | Request/response validation (FastAPI dep)  |

```bash
pip install fastapi uvicorn aiohttp aiosqlite --break-system-packages
```

### Frontend (zero build step — CDN loaded once, then vendored)

| Library                      | Purpose                                 |
|------------------------------|-----------------------------------------|
| Alpine.js 3.x                | Lightweight reactivity, no build step   |
| Chart.js 4.x                 | Canvas charts (line, bar, box)          |
| chartjs-plugin-annotation    | Threshold lines on charts               |

All CDN assets are fetched once on first startup by the backend and saved to
`static/vendor/`. Subsequent loads are fully offline.

### Database

**SQLite** file at `~/.vllm_bench/bench.db`.

### Python Version

`>= 3.11` (uses `asyncio.TaskGroup`, `match`)

---

## Directory Layout

```
vllm_bench_gui/
├── main.py                   # Entry point — starts uvicorn on port 7842
├── CLAUDE.md                 # This file
├── requirements.txt
│
├── api/
│   ├── __init__.py
│   ├── routes_servers.py     # CRUD for server profiles
│   ├── routes_benchmark.py   # Start/stop run, SSE progress stream
│   ├── routes_results.py     # Query historical runs, export
│   └── routes_backup.py      # DB + settings backup/restore
│
├── core/
│   ├── __init__.py
│   ├── benchmark.py          # Async benchmark engine (ported from vllm_benchmark.py)
│   ├── models.py             # Pydantic models: ServerProfile, BenchmarkConfig, RunResult
│   └── db.py                 # DB init, migrations, async query helpers
│
├── static/
│   ├── index.html            # Single-page app shell
│   ├── app.js                # Alpine.js app logic
│   ├── style.css             # Global styles + CSS variables
│   ├── charts.js             # Chart.js wrappers (line, bar, boxplot)
│   └── vendor/               # Auto-downloaded CDN assets (alpine, chartjs, …)
│
└── backups/                  # Auto-created; timestamped .zip backups
```

---

## Database Schema

### `servers`
```sql
CREATE TABLE servers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alias       TEXT    NOT NULL UNIQUE,
    host        TEXT    NOT NULL,
    port        INTEGER NOT NULL DEFAULT 8000,
    description TEXT,
    color       TEXT,           -- hex e.g. "#f5a623"; auto-assigned if NULL
    tags        TEXT,           -- comma-separated
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    last_pinged TEXT,           -- ISO 8601 timestamp of last ping attempt
    last_ping_ok INTEGER        -- 1 = success, 0 = failure, NULL = never pinged
);
-- No seed data. Table starts empty.
```

### `benchmark_runs`
```sql
CREATE TABLE benchmark_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT    NOT NULL UNIQUE,   -- UUID4
    server_alias     TEXT    NOT NULL,
    model            TEXT    NOT NULL,
    timestamp        TEXT    NOT NULL,          -- ISO 8601
    config_json      TEXT    NOT NULL,          -- BenchmarkConfig as JSON
    peak_tok_s       REAL,
    peak_concurrency INTEGER,
    total_requests   INTEGER,
    success_requests INTEGER,
    status           TEXT    NOT NULL DEFAULT 'running',  -- running|done|error|stopped
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

### `run_results`
```sql
CREATE TABLE run_results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT    NOT NULL REFERENCES benchmark_runs(run_id),
    prompt_key       TEXT    NOT NULL,   -- short|medium|long|coding|custom
    concurrency      INTEGER NOT NULL,
    throughput_tok_s REAL,
    avg_latency_ms   REAL,
    p50_latency_ms   REAL,
    p95_latency_ms   REAL,
    avg_ttft_ms      REAL,
    total_time_s     REAL,
    success_count    INTEGER,
    total_count      INTEGER,
    raw_json         TEXT     -- full RequestResult list for reanalysis
);
```

### `settings`
```sql
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- app_port, default_server, theme, request_timeout_s,
-- max_concurrency_cap, auto_backup, backup_keep_n, last_config_json
```

---

## REST API Specification

Base URL: `http://localhost:7842/api`

### Servers

| Method | Path                        | Description                                           |
|--------|-----------------------------|-------------------------------------------------------|
| GET    | `/servers`                  | List all server profiles                              |
| POST   | `/servers`                  | Create server profile                                 |
| PUT    | `/servers/{alias}`          | Update server profile                                 |
| DELETE | `/servers/{alias}`          | Delete server profile (+ cascade runs if confirmed)   |
| GET    | `/servers/{alias}/ping`     | Ping saved server → `{ok, model_count, latency_ms}`   |
| POST   | `/servers/test`             | Ping unsaved host/port → `{ok, model_count, latency_ms}` (no alias needed) |
| GET    | `/servers/{alias}/models`   | Fetch model list from vLLM                            |

### Benchmark

| Method | Path                         | Description                              |
|--------|------------------------------|------------------------------------------|
| POST   | `/benchmark/start`           | Start a run → `{run_id}`                 |
| POST   | `/benchmark/{run_id}/stop`   | Request graceful stop                    |
| GET    | `/benchmark/{run_id}/stream` | **SSE** — live progress events           |
| GET    | `/benchmark/{run_id}/status` | Current run status + partial results     |

SSE event format:
```json
{ "event": "progress", "data": { "prompt_key": "medium", "concurrency": 4, "done": 5, "total": 8, "tok_s": 1204.3 } }
{ "event": "result",   "data": { "prompt_key": "medium", "concurrency": 4, "throughput_tok_s": 1312.0, "avg_latency_ms": 210.4, "p95_latency_ms": 340.1, "avg_ttft_ms": 55.2, "success_count": 8, "total_count": 8 } }
{ "event": "done",     "data": { "run_id": "...", "peak_tok_s": 2104.5 } }
{ "event": "error",    "data": { "message": "..." } }
```

### Results

| Method | Path                       | Description                                     |
|--------|----------------------------|-------------------------------------------------|
| GET    | `/results`                 | List runs (filter: server, limit, offset)       |
| GET    | `/results/{run_id}`        | Full run detail + all row results               |
| DELETE | `/results/{run_id}`        | Delete run and its rows                         |
| GET    | `/results/{run_id}/export` | Download run as JSON file                       |
| GET    | `/results/compare`         | Compare ≥2 run_ids → normalised dataset         |

Query params for `/results`:
- `server_alias` — filter by server
- `limit` / `offset` — pagination (default 20 / 0)
- `order` — `desc` (default) | `asc`

### Backup

| Method | Path                   | Description                                        |
|--------|------------------------|----------------------------------------------------|
| POST   | `/backup/create`       | Create timestamped `.zip` → `{filename, size_bytes}`|
| GET    | `/backup/list`         | List existing backups                              |
| GET    | `/backup/{filename}`   | Download backup file                               |
| POST   | `/backup/restore`      | Upload `.zip` to restore DB + settings             |
| DELETE | `/backup/{filename}`   | Delete a backup file                               |

Backup ZIP contents:
```
vllm_bench_backup_<timestamp>/
  bench.db               (consistent snapshot via VACUUM INTO)
  settings_export.json
  README.txt             (app version, created_at, row counts)
```

---

## Frontend — Single Page App

**Aesthetic direction:** Feels like a real engineering dashboard.

### Colour Palette (CSS variables)
```css
--bg-base:      #0d0d0d;
--bg-panel:     #141414;
--bg-card:      #1a1a1a;
--bg-hover:     #212121;
--border:       #2a2a2a;
--accent:       #f5a623;   /* amber  — primary action */
--accent-green: #4ade80;   /* success / throughput   */
--accent-red:   #f87171;   /* error / failure        */
--accent-blue:  #60a5fa;   /* info / latency         */
--text-primary: #e8e8e8;
--text-muted:   #666666;
--font-mono:    'JetBrains Mono', 'Fira Code', monospace;
--font-ui:      'DM Sans', sans-serif;
```

### Page Structure

```
┌── HEADER ───────────────────────────────────────────────────────────┐
│  ◈ vLLM Benchmark    [server-a ●]  [server-b ○]    [⚙ Settings]   │
├── NAV TABS ─────────────────────────────────────────────────────────┤
│  [ Servers ]  [ Benchmark ]  [ History ]  [ Compare ]  [ Backup ]  │
├── CONTENT ──────────────────────────────────────────────────────────┤
│  (active tab content)                                               │
└─────────────────────────────────────────────────────────────────────┘
```

Header pills show the most recently used servers (up to 3). All status
dots are populated from the last ping result stored in the DB; never
hardcoded. On first launch, no pills appear until at least one server
is added.

### Tab: Servers

See the **Server Address Book** section above for full spec.

### Tab: Benchmark

```
┌─ SERVER & MODEL ─────────────────────────────────────────────────────┐
│ Server  [— select server — ▼]   Model  [— fetch first — ▼]  [🔄]   │
│  (populated from servers table; empty if no servers added yet)       │
└──────────────────────────────────────────────────────────────────────┘
┌─ PARAMETERS ─────────────────────────────────────────────────────────┐
│ Concurrency   [✓]1 [✓]2 [✓]4 [✓]8 [✓]12  + [Custom…]              │
│ Prompts       [✓]Short [✓]Medium [✓]Long [✓]Coding  + [Custom…]    │
│ Requests/lvl  [ 8  ]      Temperature  [ 0.0 ]    Quick mode [○]   │
└──────────────────────────────────────────────────────────────────────┘
┌─ RUN ────────────────────────────────────────────────────────────────┐
│  [▶ START]  [⏹ STOP]                                                │
│                                                                      │
│  Short   c=1   ████████████░░░░  6/8    512 tok/s                   │
│  Short   c=4   ░░░░░░░░░░░░░░░░  waiting…                           │
│  …                                                                   │
│                                                                      │
│  ┌─ Live Results ────────────────────────────────────────────────┐  │
│  │ Prompt   Conc  Tok/s    Avg Lat  P95 Lat  TTFT    OK/N        │  │
│  │ Short     1    318.4    156ms    189ms    42ms    5/5  ✓       │  │
│  └────────────────────────────────────────────────────────────── ┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### Tab: History

```
┌─ FILTER ─────────────────────────────────────────────────────────────┐
│ Server [all ▼]   Model [all ▼]    Date [──── to ────]   [Search]    │
└──────────────────────────────────────────────────────────────────────┘
┌─ RUNS ───────────────────────────────────────────────────────────────┐
│ Timestamp           Server         Model        Peak tok/s  Status   │
│ 2025-06-01 14:30    my-gpu-server  llama-70b    2104.5      ✓ done  │
│ 2025-06-01 14:00    inference-box  llama-70b    1987.3      ✓ done  │
│ …                                                   [Load more]      │
└──────────────────────────────────────────────────────────────────────┘
  [Click row → inline expand: full results table + 3 Chart.js charts]
  [Export JSON]  [Delete Run]  buttons inside expand panel
```

Charts in expand panel:
- Throughput vs Concurrency (line, one series per prompt)
- P50 / P95 Latency vs Concurrency (line, two series)
- TTFT vs Concurrency (line)

### Tab: Compare

```
Mode  (●) Two servers   ( ) Single-server history

── Two-server mode ──────────────────────────────────────────────────
Server A  [— select — ▼]    Run  [— select run — ▼]
Server B  [— select — ▼]    Run  [— select run — ▼]
Metric    [Throughput tok/s ▼]     Prompt  [Medium ▼]
[Compare]

┌─ DELTA TABLE ────────────────────────────────────────────────────┐
│ Concurrency │ Server A  │ Server B  │  Δ tok/s  │   Δ %         │
│      1      │   318.4   │   302.1   │  +16.3    │  +5.4 %       │
│      4      │  1204.5   │  1187.2   │  +17.3    │  +1.5 %       │
│      8      │  2104.5   │  1987.3   │ +117.2    │  +5.9 %       │
│     12      │  1954.1   │  1901.5   │  +52.6    │  +2.8 %       │
└──────────────────────────────────────────────────────────────────┘

[Grouped bar chart — uses each server's assigned color from address book]

── Single-server history mode ───────────────────────────────────────
Server  [— select — ▼]
Runs    [✓] 2025-06-01 14:30   [✓] 2025-06-01 16:00   [ ] 2025-05-30
Metric  [Throughput tok/s ▼]      Prompt  [Medium ▼]
[Compare]
→ Same delta table and grouped bar chart layout
```

### Tab: Backup

```
┌─ CREATE BACKUP ──────────────────────────────────────────────────────┐
│  Includes bench.db + settings                                        │
│  [📦 Create Backup Now]                                              │
└──────────────────────────────────────────────────────────────────────┘
┌─ EXISTING BACKUPS ───────────────────────────────────────────────────┐
│ Filename                           Size     [⬇ Download]  [🗑 Delete]│
│ vllm_bench_backup_20250601_1430    142 KB   [⬇]           [🗑]      │
│ …                                                                    │
└──────────────────────────────────────────────────────────────────────┘
┌─ RESTORE ────────────────────────────────────────────────────────────┐
│ [Choose .zip file]   [Upload & Restore]                              │
│ ⚠ Restoring replaces the current database and settings.             │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Benchmark Engine (`core/benchmark.py`)

Port async logic from `vllm_benchmark.py` verbatim. Public interface:

```python
async def run_benchmark(
    config: BenchmarkConfig,
    progress_cb: Callable[[ProgressEvent], Awaitable[None]],
    stop_event: asyncio.Event,
) -> BenchmarkRun: ...

async def get_models(base_url: str) -> list[str]: ...

async def ping_server(base_url: str) -> PingResult: ...
```

The API route `/benchmark/start` launches `run_benchmark()` as a background
`asyncio.Task`. Progress events are forwarded to an `asyncio.Queue` that the SSE
endpoint drains. One active task per `run_id`, tracked in a module-level dict.

---

## Prompt Library

| Key    | max_tokens | Label             |
|--------|------------|-------------------|
| short  | 50         | Short (~50 tok)   |
| medium | 512        | Medium (~512 tok) |
| long   | 2048       | Long (~2K tok)    |
| coding | 1024       | Code (~1K tok)    |
| custom | user-set   | Custom            |

Custom: textarea + max_tokens field shown when `custom` is checked.

---

## Settings

Stored in `settings` DB table (key/value pairs). Editable via `⚙ Settings` modal.

| Key                   | Default   | Description                          |
|-----------------------|-----------|--------------------------------------|
| `app_port`            | `7842`  | Uvicorn port (requires restart)                          |
| `default_server`      | `null`  | Alias of default server; set to first added server automatically |
| `theme`               | `dark`  | `dark` / `light`                                         |
| `request_timeout_s`   | `300`     | Per-request timeout                  |
| `max_concurrency_cap` | `12`      | Hard upper limit enforced in UI      |
| `auto_backup`         | `false`   | Create backup before each run starts |
| `backup_keep_n`       | `10`      | Max backup files to retain           |
| `last_config_json`    | `{}`      | Last used benchmark config (auto-saved) |

---

## Error Handling

| Scenario                         | Behaviour                                          |
|----------------------------------|----------------------------------------------------|
| Server unreachable at start      | 422 response; toast in UI; run not created in DB   |
| Request failure (< 50% of run)   | Continue; mark rows with `partial_failure` flag    |
| All requests fail                | Run status → `error`; SSE `error` event sent       |
| Stop requested                   | `stop_event.set()`; drain in-flight max 30 s; status → `stopped` |
| DB write failure                 | Log error; data held in memory for the session     |
| Backup restore while run active  | Return 409; UI shows "stop active run first"       |

---

## Implementation Steps (for Claude Code)

Confirm after each step before proceeding.

1. **Step 1 — Scaffold** — Directory structure, `__init__.py` files, `requirements.txt`.
2. **Step 2 — DB** — `core/db.py`: schema creation, migration helper, async CRUD helpers for all four tables. No seed data.
3. **Step 3 — Models** — `core/models.py`: Pydantic v2 request/response models; `BenchmarkConfig`, `RunResult`, `ServerProfile`, `PingResult`, `ProgressEvent`.
4. **Step 4 — Benchmark engine** — `core/benchmark.py`: port from `vllm_benchmark.py`; add `progress_cb` + `stop_event`; expose `get_models` and `ping_server`.
5. **Step 5 — API: servers** — `api/routes_servers.py` including `/servers/test` (ping before save); register in `main.py`.
6. **Step 6 — API: benchmark** — `api/routes_benchmark.py` with SSE streaming.
7. **Step 7 — API: results** — `api/routes_results.py` with compare endpoint.
8. **Step 8 — API: backup** — `api/routes_backup.py` with `VACUUM INTO` + ZIP packaging.
9. **Step 9 — Frontend shell** — `static/index.html`: layout, 5-tab nav (Servers, Benchmark, History, Compare, Backup), header with dynamic server pills; `static/style.css` with full dark industrial theme.
10. **Step 10 — Servers tab JS** — Address book: list, add/edit modal with `[Test Connection]`, delete guard, color picker, ping status dots.
11. **Step 11 — Benchmark tab JS** — Config form (server dropdown populated from DB), start/stop, SSE progress bars, live results table.
12. **Step 12 — History tab JS** — Run list, pagination, inline expand with Chart.js charts.
13. **Step 13 — Compare tab JS** — Delta table + grouped bar chart (server colors from DB).
14. **Step 14 — Backup tab JS** — Create, list, download, restore flows.
15. **Step 15 — Vendor assets** — Auto-download CDN files on startup; serve from `static/vendor/`.
16. **Step 16 — Polish** — Settings modal, toast notifications, empty-state screens, keyboard shortcuts `R` = start / `Esc` = stop, auto-select first server when one is added.

---

## Non-Goals

- No user authentication (local-only tool)
- No Docker packaging (runs directly on castlemac / castlejasper)
- No cloud sync or remote DB
- No vLLM server management (benchmark only, no model loading/unloading)
