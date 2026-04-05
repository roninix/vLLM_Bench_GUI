"""Benchmark start/stop routes with SSE progress streaming."""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from core.db import (
    run_create, run_get, run_update_status, run_delete,
    result_create, setting_get, server_get, result_list,
)
from core.models import BenchmarkConfig
from core import benchmark

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

# Active tasks: run_id -> {"task": asyncio.Task, "queue": asyncio.Queue, "stop_event": asyncio.Event, "done": bool}
_active_tasks: dict[str, dict[str, Any]] = {}


@router.post("/start")
async def start_benchmark(config: BenchmarkConfig, request: Request):
    """Start a benchmark run. Returns {run_id}."""
    db = request.state.db
    server = await server_get(db, config.server_alias)
    if not server:
        raise HTTPException(status_code=422, detail=f"Server '{config.server_alias}' not found")

    # Validate concurrency cap
    max_cap = await setting_get(db, "max_concurrency_cap", "12")
    try:
        cap = int(max_cap)
    except (ValueError, TypeError):
        cap = 12
    if any(c > cap for c in config.concurrency_levels):
        raise HTTPException(
            status_code=422,
            detail=f"Concurrency levels must be <= {cap}",
        )

    run_id = str(uuid.uuid4())
    base_url = f"http://{server['host']}:{server['port']}"

    # Create DB record
    await run_create(
        db,
        run_id=run_id,
        server_alias=config.server_alias,
        model=config.model,
        config_json=config.model_dump_json(),
    )

    # Set up SSE queue
    queue: asyncio.Queue = asyncio.Queue()
    stop_event = asyncio.Event()

    async def progress_cb(event: dict):
        await queue.put(event)

    # Create a dedicated DB connection for the background task (not the request-scoped one)
    from core.db import init_db
    task_db = await init_db()

    task = asyncio.create_task(
        _run_benchmark_task(
            run_id=run_id,
            config=config,
            base_url=base_url,
            db=task_db,
            progress_cb=progress_cb,
            stop_event=stop_event,
        )
    )

    _active_tasks[run_id] = {
        "task": task,
        "queue": queue,
        "stop_event": stop_event,
        "done": False,
    }

    return {"run_id": run_id}


@router.post("/{run_id}/stop")
async def stop_benchmark(run_id: str):
    """Request graceful stop of a running benchmark."""
    info = _active_tasks.get(run_id)
    if not info:
        raise HTTPException(status_code=404, detail="Run not found or not active")
    info["stop_event"].set()
    return {"stopped": True}


@router.get("/{run_id}/stream")
async def stream_benchmark(run_id: str):
    """SSE stream of benchmark progress."""
    info = _active_tasks.get(run_id)
    if not info:
        raise HTTPException(status_code=404, detail="Run not found or not active")

    async def event_generator():
        try:
            while True:
                event = await info["queue"].get()
                if event is None:
                    break
                data = json.dumps(event)
                yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{run_id}/status")
async def get_run_status(run_id: str, request: Request):
    """Get current run status and partial results."""
    db = request.state.db
    run = await run_get(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    results = await result_list(db, run_id)
    return {
        "run": run,
        "results": results,
        "active": run_id in _active_tasks and not _active_tasks[run_id].get("done", True),
    }


async def _run_benchmark_task(
    run_id: str,
    config: BenchmarkConfig,
    base_url: str,
    db,
    progress_cb,
    stop_event: asyncio.Event,
):
    """Background task that runs the benchmark and stores results."""
    try:
        summary = await benchmark.run_benchmark(
            config=config,
            base_url=base_url,
            progress_cb=progress_cb,
            stop_event=stop_event,
        )

        # Store level results
        for lr in summary["level_results"]:
            await result_create(
                db,
                run_id=run_id,
                prompt_key=lr["prompt_key"],
                concurrency=lr["concurrency"],
                throughput_tok_s=lr["throughput_tok_s"],
                avg_latency_ms=lr["avg_latency_ms"],
                p50_latency_ms=lr["p50_latency_ms"],
                p95_latency_ms=lr["p95_latency_ms"],
                avg_ttft_ms=lr["avg_ttft_ms"],
                total_time_s=lr["total_time_s"],
                success_count=lr["success_count"],
                total_count=lr["total_count"],
                raw_json=json.dumps(lr["request_details"]),
            )

        # Determine status
        stopped = stop_event.is_set()
        status = "stopped" if stopped else "done"

        await run_update_status(
            db,
            run_id,
            status,
            peak_tok_s=summary["peak_tok_s"],
            peak_concurrency=summary["peak_concurrency"],
            total_requests=summary["total_requests"],
            success_requests=summary["success_requests"],
        )

        # Send done event
        await progress_cb({
            "event": "done",
            "data": {"run_id": run_id, "peak_tok_s": summary["peak_tok_s"]},
        })
        await progress_cb(None)  # Sentinel

    except Exception as e:
        await run_update_status(db, run_id, "error")
        await progress_cb({
            "event": "error",
            "data": {"message": str(e)},
        })
        await progress_cb(None)  # Sentinel
    finally:
        if run_id in _active_tasks:
            _active_tasks[run_id]["done"] = True


def get_active_tasks():
    """Return the active tasks dict (for backup route to check)."""
    return _active_tasks
