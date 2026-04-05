"""Results query, export, and compare routes."""

import json
from typing import List
from fastapi import APIRouter, HTTPException, Query, Request, Body

router = APIRouter(prefix="/api/results", tags=["results"])


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("")
async def list_results(
    request: Request,
    server_alias: str | None = None,
    limit: int = Query(default=20, le=200),
    offset: int = Query(default=0, ge=0),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
):
    """List benchmark runs with optional server filter."""
    from core.db import run_list
    db = request.state.db
    runs = await run_list(db, server_alias=server_alias, limit=limit, offset=offset, order=order)
    return runs


# ── Compare — MUST be before /{run_id} so FastAPI matches it first ────────────

@router.get("/compare")
async def compare_runs(
    request: Request,
    run_a_id: str = Query(...),
    run_b_id: str = Query(...),
    prompt_key: str = Query(default="medium"),
    metric: str = Query(default="throughput_tok_s"),
):
    """Compare two runs → normalised delta dataset."""
    from core.db import run_get, result_list
    db = request.state.db
    run_a = await run_get(db, run_a_id)
    run_b = await run_get(db, run_b_id)
    if not run_a:
        raise HTTPException(status_code=404, detail=f"Run '{run_a_id}' not found")
    if not run_b:
        raise HTTPException(status_code=404, detail=f"Run '{run_b_id}' not found")

    results_a = await result_list(db, run_a_id)
    results_b = await result_list(db, run_b_id)

    a_by_conc = {r["concurrency"]: r for r in results_a if r["prompt_key"] == prompt_key}
    b_by_conc = {r["concurrency"]: r for r in results_b if r["prompt_key"] == prompt_key}

    all_concurrencies = sorted(set(a_by_conc.keys()) | set(b_by_conc.keys()))
    rows = []
    for conc in all_concurrencies:
        ra = a_by_conc.get(conc)
        rb = b_by_conc.get(conc)
        val_a = ra.get(metric) if ra else None
        val_b = rb.get(metric) if rb else None
        delta = None
        delta_pct = None
        if val_a is not None and val_b is not None:
            delta = round(val_a - val_b, 1)
            if val_b != 0:
                delta_pct = round((delta / val_b) * 100, 1)
        rows.append({
            "concurrency": conc,
            "value_a": val_a,
            "value_b": val_b,
            "delta": delta,
            "delta_pct": delta_pct,
        })

    return {
        "prompt_key": prompt_key,
        "metric": metric,
        "run_a_id": run_a_id,
        "run_b_id": run_b_id,
        "server_a_alias": run_a["server_alias"],
        "server_b_alias": run_b["server_alias"],
        "rows": rows,
    }


# ── Per-run routes (/{run_id}) ────────────────────────────────────────────────

@router.get("/{run_id}")
async def get_run_detail(run_id: str, request: Request):
    """Full run detail with all result rows."""
    from core.db import run_get, result_list
    db = request.state.db
    run = await run_get(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    results = await result_list(db, run_id)
    run["results"] = results
    return run


@router.delete("/{run_id}")
async def delete_run(run_id: str, request: Request):
    """Delete a run and its results."""
    from core.db import run_get, run_delete, result_delete_for_run
    db = request.state.db
    run = await run_get(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    await result_delete_for_run(db, run_id)
    success = await run_delete(db, run_id)
    if success:
        return {"deleted": True}
    raise HTTPException(status_code=500, detail="Failed to delete run")


@router.delete("")
async def delete_runs(
    request: Request,
    payload: dict = Body(..., description="Delete payload"),
):
    """Delete multiple runs and their results in batch.

    Body: {"run_ids": ["id1", "id2", ...]}
    """
    from core.db import run_delete_batch
    db = request.state.db

    run_ids = payload.get("run_ids", [])

    if not run_ids:
        raise HTTPException(status_code=400, detail="No run_ids provided")

    result = await run_delete_batch(db, run_ids)
    return result


@router.get("/{run_id}/export")
async def export_run(run_id: str, request: Request):
    """Export run as JSON."""
    from core.db import run_get, result_list
    db = request.state.db
    run = await run_get(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    results = await result_list(db, run_id)
    config = json.loads(run["config_json"])
    return {
        "run_id": run["run_id"],
        "server_alias": run["server_alias"],
        "model": run["model"],
        "timestamp": run["timestamp"],
        "status": run["status"],
        "peak_tok_s": run["peak_tok_s"],
        "config": config,
        "results": results,
    }
