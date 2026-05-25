"""Async SQLite helpers for vLLM Benchmark GUI."""

import aiosqlite
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

DB_DIR = Path.home() / ".vllm_bench"
DB_PATH = DB_DIR / "bench.db"


def _color_palette():
    """Fixed palette of chart colours for servers."""
    return [
        "#f5a623", "#4ade80", "#60a5fa", "#f87171",
        "#a78bfa", "#fb923c", "#2dd4bf", "#e879f9",
        "#84cc16", "#fbbf24", "#38bdf8", "#f472b6",
    ]


async def init_db(db_path: str | Path | None = None) -> aiosqlite.Connection:
    """Create tables if they don't exist and return an open connection."""
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    db = await aiosqlite.connect(str(path))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")

    await db.executescript("""
        CREATE TABLE IF NOT EXISTS servers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            alias       TEXT    NOT NULL UNIQUE,
            host        TEXT    NOT NULL,
            port        INTEGER NOT NULL DEFAULT 8000,
            description TEXT,
            color       TEXT,
            tags        TEXT,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            last_pinged TEXT,
            last_ping_ok INTEGER
        );

        CREATE TABLE IF NOT EXISTS benchmark_runs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id           TEXT    NOT NULL UNIQUE,
            server_alias     TEXT    NOT NULL,
            model            TEXT    NOT NULL,
            timestamp        TEXT    NOT NULL,
            config_json      TEXT    NOT NULL,
            peak_tok_s       REAL,
            peak_concurrency INTEGER,
            total_requests   INTEGER,
            success_requests INTEGER,
            status           TEXT    NOT NULL DEFAULT 'running',
            created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS run_results (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id           TEXT    NOT NULL REFERENCES benchmark_runs(run_id),
            prompt_key       TEXT    NOT NULL,
            concurrency      INTEGER NOT NULL,
            throughput_tok_s REAL,
            avg_latency_ms   REAL,
            p50_latency_ms   REAL,
            p95_latency_ms   REAL,
            avg_ttft_ms      REAL,
            total_time_s     REAL,
            success_count    INTEGER,
            total_count      INTEGER,
            raw_json         TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    await db.commit()
    return db


# ── Colour assignment ─────────────────────────────────────────────────────────

async def assign_server_color(db: aiosqlite.Connection) -> str:
    """Pick the next unused colour from the palette, or random if exhausted."""
    async with db.execute("SELECT color FROM servers WHERE color IS NOT NULL") as cur:
        rows = await cur.fetchall()
    used = {r[0] for r in rows}
    for c in _color_palette():
        if c not in used:
            return c
    import random
    return f"#{random.randint(0, 0xFFFFFF):06x}"


# ── Server CRUD ───────────────────────────────────────────────────────────────

async def server_create(
    db: aiosqlite.Connection,
    alias: str,
    host: str,
    port: int,
    description: str | None = None,
    color: str | None = None,
    tags: str | None = None,
) -> dict:
    if color is None:
        color = await assign_server_color(db)
    await db.execute(
        "INSERT INTO servers (alias, host, port, description, color, tags) VALUES (?, ?, ?, ?, ?, ?)",
        (alias, host, port, description, color, tags),
    )
    await db.commit()
    return await server_get(db, alias)


async def server_get(db: aiosqlite.Connection, alias: str) -> dict | None:
    async with db.execute(
        "SELECT * FROM servers WHERE alias = ?", (alias,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def server_list(db: aiosqlite.Connection) -> list[dict]:
    async with db.execute("SELECT * FROM servers ORDER BY created_at DESC") as cur:
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def server_update(
    db: aiosqlite.Connection,
    alias: str,
    **fields: Any,
) -> dict | None:
    allowed = {"host", "port", "description", "color", "tags"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return await server_get(db, alias)
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [alias]
    await db.execute(f"UPDATE servers SET {set_clause} WHERE alias = ?", vals)
    await db.commit()
    return await server_get(db, alias)


async def server_delete(db: aiosqlite.Connection, alias: str) -> bool:
    cur = await db.execute("DELETE FROM servers WHERE alias = ?", (alias,))
    await db.commit()
    return cur.rowcount > 0


async def server_ping_update(
    db: aiosqlite.Connection, alias: str, ok: bool
) -> None:
    await db.execute(
        "UPDATE servers SET last_pinged = ?, last_ping_ok = ? WHERE alias = ?",
        (datetime.now().isoformat(), 1 if ok else 0, alias),
    )
    await db.commit()


async def server_run_count(db: aiosqlite.Connection, alias: str) -> int:
    async with db.execute(
        "SELECT COUNT(*) FROM benchmark_runs WHERE server_alias = ?", (alias,)
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else 0


# ── Benchmark run CRUD ────────────────────────────────────────────────────────

async def run_create(
    db: aiosqlite.Connection,
    run_id: str,
    server_alias: str,
    model: str,
    config_json: str,
    timestamp: str | None = None,
) -> dict:
    ts = timestamp or datetime.now().isoformat()
    await db.execute(
        "INSERT INTO benchmark_runs (run_id, server_alias, model, timestamp, config_json) VALUES (?, ?, ?, ?, ?)",
        (run_id, server_alias, model, ts, config_json),
    )
    await db.commit()
    return await run_get(db, run_id)


async def run_get(db: aiosqlite.Connection, run_id: str) -> dict | None:
    async with db.execute(
        "SELECT * FROM benchmark_runs WHERE run_id = ?", (run_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def run_list(
    db: aiosqlite.Connection,
    server_alias: str | None = None,
    limit: int = 20,
    offset: int = 0,
    order: str = "desc",
) -> list[dict]:
    query = "SELECT * FROM benchmark_runs"
    params: list = []
    if server_alias:
        query += " WHERE server_alias = ?"
        params.append(server_alias)
    query += f" ORDER BY timestamp {'DESC' if order == 'desc' else 'ASC'} LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def run_update_status(
    db: aiosqlite.Connection,
    run_id: str,
    status: str,
    peak_tok_s: float | None = None,
    peak_concurrency: int | None = None,
    total_requests: int | None = None,
    success_requests: int | None = None,
) -> None:
    fields = ["status = ?"]
    vals: list = [status]
    if peak_tok_s is not None:
        fields.append("peak_tok_s = ?")
        vals.append(peak_tok_s)
    if peak_concurrency is not None:
        fields.append("peak_concurrency = ?")
        vals.append(peak_concurrency)
    if total_requests is not None:
        fields.append("total_requests = ?")
        vals.append(total_requests)
    if success_requests is not None:
        fields.append("success_requests = ?")
        vals.append(success_requests)
    vals.append(run_id)
    await db.execute(
        f"UPDATE benchmark_runs SET {', '.join(fields)} WHERE run_id = ?", vals
    )
    await db.commit()


async def run_delete(db: aiosqlite.Connection, run_id: str) -> bool:
    await db.execute("DELETE FROM run_results WHERE run_id = ?", (run_id,))
    cur = await db.execute("DELETE FROM benchmark_runs WHERE run_id = ?", (run_id,))
    await db.commit()
    return cur.rowcount > 0


async def run_delete_batch(db: aiosqlite.Connection, run_ids: list[str]) -> dict:
    """Delete multiple runs. Returns dict with 'deleted' and 'failed' lists."""
    deleted = []
    failed = []

    for run_id in run_ids:
        try:
            await db.execute("DELETE FROM run_results WHERE run_id = ?", (run_id,))
            cur = await db.execute("DELETE FROM benchmark_runs WHERE run_id = ?", (run_id,))
            if cur.rowcount > 0:
                deleted.append(run_id)
            else:
                failed.append(run_id)
        except Exception:
            failed.append(run_id)

    await db.commit()
    return {"deleted": deleted, "failed": failed}


# ── Run results CRUD ─────────────────────────────────────────────────────────

async def result_create(
    db: aiosqlite.Connection,
    run_id: str,
    prompt_key: str,
    concurrency: int,
    throughput_tok_s: float | None = None,
    avg_latency_ms: float | None = None,
    p50_latency_ms: float | None = None,
    p95_latency_ms: float | None = None,
    avg_ttft_ms: float | None = None,
    total_time_s: float | None = None,
    success_count: int | None = None,
    total_count: int | None = None,
    raw_json: str | None = None,
) -> int:
    cur = await db.execute(
        """INSERT INTO run_results
           (run_id, prompt_key, concurrency, throughput_tok_s, avg_latency_ms,
            p50_latency_ms, p95_latency_ms, avg_ttft_ms, total_time_s,
            success_count, total_count, raw_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id, prompt_key, concurrency, throughput_tok_s,
            avg_latency_ms, p50_latency_ms, p95_latency_ms, avg_ttft_ms,
            total_time_s, success_count, total_count, raw_json,
        ),
    )
    await db.commit()
    return cur.lastrowid


async def result_list(db: aiosqlite.Connection, run_id: str) -> list[dict]:
    async with db.execute(
        "SELECT * FROM run_results WHERE run_id = ? ORDER BY prompt_key, concurrency",
        (run_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def result_delete_for_run(db: aiosqlite.Connection, run_id: str) -> None:
    await db.execute("DELETE FROM run_results WHERE run_id = ?", (run_id,))
    await db.commit()


# ── Settings CRUD ─────────────────────────────────────────────────────────────

async def setting_get(
    db: aiosqlite.Connection, key: str, default: str | None = None
) -> str | None:
    async with db.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else default


async def setting_set(db: aiosqlite.Connection, key: str, value: str) -> None:
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
        (key, value, value),
    )
    await db.commit()


async def setting_list(db: aiosqlite.Connection) -> dict[str, str]:
    async with db.execute("SELECT key, value FROM settings") as cur:
        rows = await cur.fetchall()
    return {r[0]: r[1] for r in rows}


async def setting_delete(db: aiosqlite.Connection, key: str) -> bool:
    cur = await db.execute("DELETE FROM settings WHERE key = ?", (key,))
    await db.commit()
    return cur.rowcount > 0
