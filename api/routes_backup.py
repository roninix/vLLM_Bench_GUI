"""Backup/restore routes — VACUUM INTO + ZIP packaging."""

import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse

from core.db import DB_PATH, DB_DIR, setting_list, setting_set, server_list, run_list
from core import db as db_module
from api.routes_benchmark import get_active_tasks

BACKUP_DIR = Path(__file__).parent.parent / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

APP_VERSION = "1.0.0"

router = APIRouter(prefix="/api/backup", tags=["backup"])


def _backup_filename() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")  # %f = microseconds
    return f"vllm_bench_backup_{ts}"


@router.post("/create")
async def create_backup(request: Request):
    """Create a timestamped .zip backup of the database and settings."""
    db = request.state.db
    filename = _backup_filename()
    zip_path = BACKUP_DIR / f"{filename}.zip"

    # Create temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        folder = Path(tmpdir) / filename
        folder.mkdir()

        # VACUUM INTO a temp copy for consistency
        db_copy_path = folder / "bench.db"
        await db.execute(f"VACUUM INTO '{db_copy_path}'")

        # Export settings
        settings = await setting_list(db)
        (folder / "settings_export.json").write_text(
            json.dumps(settings, indent=2), encoding="utf-8"
        )

        # README
        servers = await server_list(db)
        runs = await run_list(db, limit=999999)
        (folder / "README.txt").write_text(
            f"vLLM Benchmark Backup\n"
            f"Version: {APP_VERSION}\n"
            f"Created: {datetime.now().isoformat()}\n"
            f"Servers: {len(servers)}\n"
            f"Runs: {len(runs)}\n",
            encoding="utf-8",
        )

        # Create ZIP
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in folder.rglob("*"):
                if fpath.is_file():
                    zf.write(fpath, fpath.relative_to(folder.parent))

    file_size = zip_path.stat().st_size
    return {"filename": f"{filename}.zip", "size_bytes": file_size}


@router.get("/list")
async def list_backups():
    """List existing backup files."""
    backups = []
    for f in sorted(BACKUP_DIR.glob("vllm_bench_backup_*.zip"), reverse=True):
        stat = f.stat()
        backups.append({
            "filename": f.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return backups


@router.get("/{filename}")
async def download_backup(filename: str):
    """Download a backup file."""
    file_path = BACKUP_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(
        str(file_path),
        filename=filename,
        media_type="application/zip",
    )


@router.post("/restore")
async def restore_backup(request: Request, file: UploadFile = File(...)):
    """Upload a .zip backup to restore DB + settings."""
    db = request.state.db

    # Check for active runs
    active = get_active_tasks()
    active_runs = [rid for rid, info in active.items() if not info.get("done", True)]
    if active_runs:
        raise HTTPException(
            status_code=409,
            detail=f"Stop active run(s) first: {active_runs}",
        )

    # Save uploaded file to temp
    with tempfile.TemporaryDirectory() as tmpdir:
        upload_path = Path(tmpdir) / file.filename
        content = await file.read()
        upload_path.write_bytes(content)

        # Validate ZIP
        if not zipfile.is_zipfile(upload_path):
            raise HTTPException(status_code=400, detail="Invalid ZIP file")

        with zipfile.ZipFile(upload_path, "r") as zf:
            # Extract DB
            db_files = [n for n in zf.namelist() if n.endswith("bench.db")]
            if not db_files:
                raise HTTPException(status_code=400, detail="No bench.db found in backup")

            # Extract settings
            settings_files = [n for n in zf.namelist() if "settings_export" in n]

            # Extract to temp
            extract_dir = Path(tmpdir) / "restore"
            zf.extractall(extract_dir)

            # Replace DB
            restored_db_path = extract_dir / db_files[0]
            if restored_db_path.exists():
                # Close current db connection
                await db.close()
                shutil.copy2(str(restored_db_path), str(DB_PATH))

            # Restore settings
            if settings_files:
                settings_path = extract_dir / settings_files[0]
                if settings_path.exists():
                    settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
                    for key, value in settings_data.items():
                        new_db = await db_module.init_db()
                        await setting_set(new_db, key, value)
                        await new_db.close()

    return {"restored": True, "message": "Database and settings restored successfully"}


@router.delete("/{filename}")
async def delete_backup(filename: str):
    """Delete a backup file."""
    file_path = BACKUP_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    file_path.unlink()
    return {"deleted": True}
