"""Server profile CRUD routes."""

from fastapi import APIRouter, HTTPException, Request
from core.db import (
    server_create, server_get, server_list, server_update,
    server_delete, server_ping_update, server_run_count,
)
from core.models import ServerProfileCreate, ServerProfileUpdate, ServerTestRequest
from core import benchmark

router = APIRouter(prefix="/api/servers", tags=["servers"])


@router.get("")
async def list_servers(request: Request):
    """List all server profiles."""
    db = request.state.db
    servers = await server_list(db)
    # Enrich with run counts
    enriched = []
    for s in servers:
        rc = await server_run_count(db, s["alias"])
        s["run_count"] = rc
        enriched.append(s)
    return enriched


@router.post("")
async def create_server(body: ServerProfileCreate, request: Request):
    """Create a new server profile."""
    db = request.state.db
    existing = await server_get(db, body.alias)
    if existing:
        raise HTTPException(status_code=409, detail=f"Server '{body.alias}' already exists")
    result = await server_create(
        db,
        alias=body.alias,
        host=body.host,
        port=body.port,
        description=body.description,
        color=body.color,
        tags=body.tags,
    )
    return result


@router.put("/{alias}")
async def update_server(alias: str, body: ServerProfileUpdate, request: Request):
    """Update a server profile."""
    db = request.state.db
    existing = await server_get(db, alias)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Server '{alias}' not found")
    update_fields = body.model_dump(exclude_unset=True)
    result = await server_update(db, alias, **update_fields)
    return result


@router.delete("/{alias}")
async def delete_server(alias: str, request: Request):
    """Delete a server profile (cascade deletes runs)."""
    db = request.state.db
    existing = await server_get(db, alias)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Server '{alias}' not found")
    rc = await server_run_count(db, alias)

    # Cascade: delete all runs and their results for this server
    from core.db import run_list, result_delete_for_run, run_delete
    runs = await run_list(db, server_alias=alias, limit=999999)
    for run in runs:
        await result_delete_for_run(db, run["run_id"])
        await run_delete(db, run["run_id"])

    success = await server_delete(db, alias)
    if success:
        return {"deleted": True, "runs_deleted": rc}
    raise HTTPException(status_code=500, detail="Failed to delete server")


@router.get("/{alias}/ping")
async def ping_server(alias: str, request: Request):
    """Ping a saved server."""
    db = request.state.db
    existing = await server_get(db, alias)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Server '{alias}' not found")
    base_url = f"http://{existing['host']}:{existing['port']}"
    result = await benchmark.ping_server(base_url)
    await server_ping_update(db, alias, result["ok"])
    return result


@router.post("/test")
async def test_connection(body: ServerTestRequest):
    """Ping an unsaved host/port."""
    base_url = f"http://{body.host}:{body.port}"
    result = await benchmark.ping_server(base_url)
    return result


@router.get("/{alias}/models")
async def get_models(alias: str, request: Request):
    """Fetch model list from a saved server."""
    db = request.state.db
    existing = await server_get(db, alias)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Server '{alias}' not found")
    base_url = f"http://{existing['host']}:{existing['port']}"
    models = await benchmark.get_models(base_url)
    return {"models": models}
