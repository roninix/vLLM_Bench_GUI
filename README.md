# vLLM Benchmark GUI

A locally-hosted web application for benchmarking vLLM inference servers. Manage server profiles, run parametric benchmarks, compare results historically and cross-server, and back up your data — all from a single browser tab at `http://localhost:7842`.

![vLLM Benchmark](https://img.shields.io/badge/vLLM-Benchmark-orange)
![Python](https://img.shields.io/badge/Python-%E2%89%A53.11-blue)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Features

- **Server Address Book** — CRUD for vLLM server profiles with color coding, tags, and live ping status
- **Parametric Benchmarking** — Test concurrency (1, 2, 4, 8, 12 + custom) across multiple prompt sizes with real-time SSE progress bars
- **Live Results** — Throughput, latency (avg / P50 / P95), TTFT, and success rates streamed as the benchmark runs
- **History** — Filterable run list with inline expand showing Chart.js visualizations (throughput, latency, TTFT vs concurrency)
- **Cross-Server Compare** — Delta table and grouped bar chart comparing any two runs from any two servers
- **Backup / Restore** — Timestamped ZIP backups of the SQLite database and settings
- **Zero external dependencies at runtime** — All CDN assets (Alpine.js, Chart.js) are vendored on first startup and served locally
<img width="1462" height="1154" alt="image" src="https://github.com/user-attachments/assets/9dec4c6c-e600-4b9b-90ba-9923c9debc36" />

<img width="1457" height="1218" alt="image" src="https://github.com/user-attachments/assets/648819c4-26ac-4713-af98-d1b642f39bbb" />

<img width="1457" height="1218" alt="image" src="https://github.com/user-attachments/assets/8cd4d93a-21e9-4177-ab9b-f485fbb42f5b" />



---

## Installation

### Prerequisites

- **Python ≥ 3.11** (uses `asyncio.TaskGroup`, `match`)
- A running vLLM server to benchmark (any OpenAI-compatible endpoint)

### Install Dependencies

```bash
pip install fastapi uvicorn aiohttp aiosqlite pydantic --break-system-packages
```

Or from the `requirements.txt`:

```bash
pip install -r requirements.txt --break-system-packages
```

---

## Running

### Start the Server

```bash
python main.py
```

The app will:
1. Create the SQLite database at `~/.vllm_bench/bench.db` (first run only)
2. Download vendor assets (Alpine.js, Chart.js) into `static/vendor/` (first run only)
3. Start on port **7842**

Open your browser to:

```
http://localhost:7842
```

### Custom Port

Edit the `app_port` setting in the Settings modal (⚙ gear icon), or change the default in `main.py`:

```python
port = 7842  # change this
```

A restart is required for port changes to take effect.

---

## Using the App

### 1. Add a Server

1. Navigate to the **Servers** tab
2. Click **+ Add Server**
3. Fill in the details:

   | Field         | Required | Notes                                     |
   |---------------|----------|-------------------------------------------|
   | `alias`       | ✓        | Short unique name (no spaces)             |
   | `host`        | ✓        | IP address or hostname                    |
   | `port`        | ✓        | vLLM server port (default 8000)           |
   | `description` |          | Free text (hardware notes, etc.)          |
   | `color`       |          | Hex colour for chart series (auto-assigned) |
   | `tags`        |          | Comma-separated, for filtering            |

4. Click **Test Connection** to verify reachability before saving
5. Click **Save**

The server status dot shows: 🟢 reachable, 🔴 unreachable, ⚪ never pinged.

### 2. Run a Benchmark

1. Navigate to the **Benchmark** tab
2. Select a server and model (models are fetched automatically)
3. Configure parameters:

   | Parameter         | Default        | Notes                                    |
   |-------------------|----------------|------------------------------------------|
   | **Concurrency**   | 1, 2, 4        | Check levels; add custom values           |
   | **Prompts**       | all checked    | Short (~50), Medium (~512), Long (~2K), Code (~1K) |
   | **Requests/level**| 8              | Number of requests per concurrency level |
   | **Temperature**   | 0.0            | Model temperature                        |
   | **Quick mode**    | Off            | Reduces requests for faster testing      |

4. Click **▶ START**
5. Watch real-time progress bars and the live results table
6. Click **⏹ STOP** to abort early

**Keyboard shortcuts:**
- `R` — Start benchmark (when not running)
- `Esc` — Stop benchmark (when running)

### 3. View History

1. Navigate to the **History** tab
2. Filter by server name
3. Click **Load** on any run to expand:
   - Throughput vs Concurrency chart
   - Latency (P50 / P95) vs Concurrency chart
   - TTFT vs Concurrency chart
   - Full results table
   - Export JSON / Delete run buttons

**Bulk Delete:** Select multiple runs with checkboxes and click "Delete Selected" to remove them at once.

### 4. Compare Runs

1. Navigate to the **Compare** tab
2. Select **Two servers** mode
3. Choose Server A → pick a run, then Server B → pick a run
4. Select the metric (Throughput / Avg Latency / P95 Latency / TTFT) and prompt type
5. Click **Compare**

A delta table and grouped bar chart show the difference, colored by each server's assigned color from the address book.

### 5. Backup & Restore

1. Navigate to the **Backup** tab
2. Click **📦 Create Backup Now** — a timestamped ZIP is created containing the database and settings
3. Download or delete existing backups as needed
4. To restore: select a `.zip` file and click **Upload & Restore** (requires stopping any active benchmark run first)

> ⚠ Restoring replaces the current database and settings entirely.

---

## Directory Structure

```
vllm_bench_gui/
├── main.py                       # Entry point — starts uvicorn
├── README.md                     # This file
├── requirements.txt              # Python dependencies
├── pytest.ini                    # Test configuration
│
├── api/
│   ├── __init__.py
│   ├── routes_servers.py         # Server CRUD + ping + models
│   ├── routes_benchmark.py       # Start/stop run + SSE progress stream
│   ├── routes_results.py         # Query, export, compare runs
│   └── routes_backup.py          # Create/list/download/restore backups
│
├── core/
│   ├── __init__.py
│   ├── benchmark.py              # Async benchmark engine
│   ├── models.py                 # Pydantic v2 request/response models
│   └── db.py                     # SQLite schema + async CRUD helpers
│
├── static/
│   ├── index.html                # Single-page app shell
│   ├── app.js                    # Alpine.js application logic
│   ├── style.css                 # Industrial dark theme
│   └── vendor/                   # Alpine.js, Chart.js, annotations plugin
│
├── backups/                      # Timestamped .zip backup files
└── tests/
    ├── test_all.py               # 73 core tests
    └── test_edge_cases.py        # 28 edge case tests
```

---

## Database

SQLite file at `~/.vllm_bench/bench.db` with four tables:

| Table              | Purpose                        |
|--------------------|--------------------------------|
| `servers`          | Server profiles (alias, host, port, color, tags, ping status) |
| `benchmark_runs`   | Run metadata (status, peak throughput, config JSON) |
| `run_results`      | Per-level results (throughput, latency, TTFT per prompt/concurrency) |
| `settings`         | App settings (port, timeout, concurrency cap, etc.) |

No seed data. The database starts completely empty.

---

## REST API

Base URL: `http://localhost:7842/api`

### Servers

| Method | Path                      | Description                         |
|--------|---------------------------|-------------------------------------|
| GET    | `/servers`                | List all server profiles            |
| POST   | `/servers`                | Create a server profile             |
| PUT    | `/servers/{alias}`        | Update a server profile             |
| DELETE | `/servers/{alias}`        | Delete server (cascades to runs)    |
| GET    | `/servers/{alias}/ping`   | Ping a saved server                 |
| POST   | `/servers/test`           | Test connection (unsaved host/port) |
| GET    | `/servers/{alias}/models` | Fetch model list from vLLM          |

### Benchmark

| Method | Path                         | Description                      |
|--------|------------------------------|----------------------------------|
| POST   | `/benchmark/start`           | Start a run → `{run_id}`         |
| POST   | `/benchmark/{run_id}/stop`   | Request graceful stop            |
| GET    | `/benchmark/{run_id}/stream` | **SSE** — live progress events   |
| GET    | `/benchmark/{run_id}/status` | Current run status + results     |

### Results

| Method | Path                       | Description                    |
|--------|----------------------------|--------------------------------|
| GET    | `/results`                 | List runs (filter: server, limit, offset) |
| GET    | `/results/{run_id}`        | Full run detail + all results  |
| DELETE | `/results/{run_id}`        | Delete a run                   |
| DELETE | `/results`                 | Delete multiple runs (body: `{"run_ids": [...]}`) |
| GET    | `/results/{run_id}/export` | Download run as JSON           |
| GET    | `/results/compare`         | Compare two runs → delta data  |

### Backup

| Method | Path                   | Description                     |
|--------|------------------------|---------------------------------|
| POST   | `/backup/create`       | Create timestamped `.zip`       |
| GET    | `/backup/list`         | List existing backups           |
| GET    | `/backup/{filename}`   | Download backup file            |
| POST   | `/backup/restore`      | Upload `.zip` to restore DB     |
| DELETE | `/backup/{filename}`   | Delete a backup file            |

---

## Running Tests

```bash
python -m pytest tests/ -v
```

101 tests covering database CRUD, Pydantic model validation, benchmark engine, all API routes, edge cases (cascade deletes, pagination, asymmetric compare, frontend serving).

---

## Tech Stack

| Layer    | Technology                              |
|----------|-----------------------------------------|
| Backend  | FastAPI + Uvicorn (ASGI)                |
| DB       | SQLite via aiosqlite (async WAL mode)   |
| HTTP     | aiohttp (async calls to vLLM endpoints) |
| Frontend | Alpine.js 3.x (reactive, zero build)    |
| Charts   | Chart.js 4.x + annotations plugin       |
| Tests    | pytest + httpx (ASGI test client)       |
| Python   | ≥ 3.11                                  |

---

## Non-Goals

- No user authentication (local-only tool)
- No Docker packaging (runs directly on host)
- No cloud sync or remote database
- No vLLM server management (benchmark only, no model loading/unloading)
