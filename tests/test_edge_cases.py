"""Additional edge case and integration tests."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from httpx import ASGITransport, AsyncClient

from core.db import init_db, run_create, result_create, server_create
from main import create_app


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    tmp = tempfile.mktemp(suffix=".db")
    db_conn = await init_db(tmp)
    yield db_conn
    await db_conn.close()
    try:
        os.unlink(tmp)
    except OSError:
        pass


@pytest_asyncio.fixture
async def client(db):
    app = create_app()
    from main import DBMiddleware

    class TestDBMiddleware(DBMiddleware):
        async def dispatch(self, request, call_next):
            request.state.db = db
            try:
                return await call_next(request)
            finally:
                pass

    app.user_middleware = []
    app.add_middleware(TestDBMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Edge Case Tests ──────────────────────────────────────────────────────────

class TestServerEdgeCases:
    """Edge cases for server management."""

    @pytest.mark.asyncio
    async def test_create_server_with_color(self, client):
        r = await client.post("/api/servers", json={
            "alias": "colored-srv",
            "host": "1.1.1.1",
            "port": 8000,
            "color": "#ff0000",
        })
        assert r.status_code == 200
        assert r.json()["color"] == "#ff0000"

    @pytest.mark.asyncio
    async def test_update_server_color_only(self, client):
        await client.post("/api/servers", json={"alias": "c", "host": "1.1.1.1", "port": 8000})
        r = await client.put("/api/servers/c", json={"color": "#abcdef"})
        assert r.status_code == 200
        assert r.json()["color"] == "#abcdef"

    @pytest.mark.asyncio
    async def test_create_server_invalid_port_zero(self, client):
        r = await client.post("/api/servers", json={"alias": "bad", "host": "1.1.1.1", "port": 0})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_create_server_port_too_high(self, client):
        r = await client.post("/api/servers", json={"alias": "bad", "host": "1.1.1.1", "port": 70000})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_server_cascades_runs(self, client, db):
        # Create server + run
        await client.post("/api/servers", json={"alias": "del-cascade", "host": "1.1.1.1", "port": 8000})
        await run_create(db, "run-1", "del-cascade", "model", "{}")
        await result_create(db, "run-1", "short", 1, throughput_tok_s=100.0)

        r = await client.delete("/api/servers/del-cascade")
        assert r.status_code == 200
        assert r.json()["runs_deleted"] == 1

        # Verify run is gone
        r2 = await client.get("/api/results/run-1")
        assert r2.status_code == 404

    @pytest.mark.asyncio
    async def test_ping_server_unreachable_updates_status(self, client):
        await client.post("/api/servers", json={"alias": "ping-test", "host": "127.0.0.1", "port": 19999})
        r = await client.get("/api/servers/ping-test/ping")
        assert r.status_code == 200
        assert r.json()["ok"] is False

        # Verify DB updated
        r2 = await client.get("/api/servers")
        srv = [s for s in r2.json() if s["alias"] == "ping-test"][0]
        assert srv["last_ping_ok"] == 0


class TestBenchmarkEdgeCases:
    """Edge cases for benchmark API."""

    @pytest.mark.asyncio
    async def test_start_concurrency_exceeds_cap(self, client, db):
        from core.db import setting_set
        await setting_set(db, "max_concurrency_cap", "4")
        await client.post("/api/servers", json={"alias": "cap-srv", "host": "127.0.0.1", "port": 19999})
        r = await client.post("/api/benchmark/start", json={
            "server_alias": "cap-srv",
            "model": "m",
            "concurrency_levels": [1, 8],  # 8 > cap of 4
            "prompt_keys": ["short"],
        })
        assert r.status_code == 422
        assert "must be <=" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_start_empty_concurrency(self, client):
        await client.post("/api/servers", json={"alias": "s", "host": "1.1.1.1", "port": 8000})
        r = await client.post("/api/benchmark/start", json={
            "server_alias": "s",
            "model": "m",
            "concurrency_levels": [],  # Empty
            "prompt_keys": ["short"],
        })
        assert r.status_code == 422  # Pydantic min_length=1

    @pytest.mark.asyncio
    async def test_start_empty_prompts(self, client):
        await client.post("/api/servers", json={"alias": "s", "host": "1.1.1.1", "port": 8000})
        r = await client.post("/api/benchmark/start", json={
            "server_alias": "s",
            "model": "m",
            "concurrency_levels": [1],
            "prompt_keys": [],  # Empty
        })
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_benchmark_run_stored_in_db(self, client, db):
        await client.post("/api/servers", json={"alias": "db-srv", "host": "127.0.0.1", "port": 19999})
        r = await client.post("/api/benchmark/start", json={
            "server_alias": "db-srv",
            "model": "test-model",
            "concurrency_levels": [1],
            "prompt_keys": ["short"],
            "num_requests": 1,
        })
        assert r.status_code == 200
        run_id = r.json()["run_id"]

        # Verify in results
        import asyncio
        await asyncio.sleep(0.5)  # Let task start
        r2 = await client.get(f"/api/results/{run_id}")
        assert r2.status_code == 200
        data = r2.json()
        assert data["server_alias"] == "db-srv"
        assert data["model"] == "test-model"


class TestResultsEdgeCases:
    """Edge cases for results API."""

    @pytest.mark.asyncio
    async def test_results_order_asc(self, client, db):
        await run_create(db, "r1", "s", "m", "{}")
        await run_create(db, "r2", "s", "m", "{}")
        await run_create(db, "r3", "s", "m", "{}")
        r = await client.get("/api/results?order=asc&limit=10")
        ids = [x["run_id"] for x in r.json()]
        assert ids == ["r1", "r2", "r3"]

    @pytest.mark.asyncio
    async def test_results_pagination(self, client, db):
        for i in range(10):
            await run_create(db, f"p{i}", "s", "m", "{}")
        r = await client.get("/api/results?limit=3&offset=0&order=asc")
        assert len(r.json()) == 3
        r2 = await client.get("/api/results?limit=3&offset=9&order=asc")
        assert len(r2.json()) == 1

    @pytest.mark.asyncio
    async def test_compare_same_server(self, client, db):
        await run_create(db, "ca", "srv", "m", "{}")
        await run_create(db, "cb", "srv", "m", "{}")
        await result_create(db, "ca", "medium", 1, throughput_tok_s=300.0)
        await result_create(db, "ca", "medium", 4, throughput_tok_s=1200.0)
        await result_create(db, "cb", "medium", 1, throughput_tok_s=280.0)
        await result_create(db, "cb", "medium", 4, throughput_tok_s=1100.0)

        r = await client.get("/api/results/compare?run_a_id=ca&run_b_id=cb&prompt_key=medium&metric=throughput_tok_s")
        assert r.status_code == 200
        data = r.json()
        assert len(data["rows"]) == 2
        # c=1: 300 - 280 = 20
        assert data["rows"][0]["delta"] == 20.0
        # c=4: 1200 - 1100 = 100
        assert data["rows"][1]["delta"] == 100.0

    @pytest.mark.asyncio
    async def test_compare_asymmetric_concurrency(self, client, db):
        await run_create(db, "sa", "s", "m", "{}")
        await run_create(db, "sb", "s", "m", "{}")
        await result_create(db, "sa", "short", 1, throughput_tok_s=300.0)
        await result_create(db, "sa", "short", 4, throughput_tok_s=1200.0)
        await result_create(db, "sb", "short", 4, throughput_tok_s=1100.0)
        # sb has no c=1 row

        r = await client.get("/api/results/compare?run_a_id=sa&run_b_id=sb&prompt_key=short&metric=throughput_tok_s")
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert len(rows) == 2
        assert rows[0]["value_a"] == 300.0
        assert rows[0]["value_b"] is None
        assert rows[0]["delta"] is None

    @pytest.mark.asyncio
    async def test_export_run(self, client, db):
        await run_create(db, "exp1", "srv", "llama", '{"model":"llama"}')
        await result_create(db, "exp1", "medium", 2, throughput_tok_s=500.0)
        r = await client.get("/api/results/exp1/export")
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == "exp1"
        assert data["model"] == "llama"
        assert len(data["results"]) == 1


class TestBackupEdgeCases:
    """Edge cases for backup API."""

    @pytest.mark.asyncio
    async def test_multiple_backups(self, client):
        await client.post("/api/backup/create")
        await client.post("/api/backup/create")
        r = await client.get("/api/backup/list")
        assert len(r.json()) >= 2

    @pytest.mark.asyncio
    async def test_restore_invalid_file(self, client):
        # Send a plain text file as "zip"
        r = await client.post(
            "/api/backup/restore",
            files={"file": ("fake.zip", b"not a zip file", "application/zip")},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_restore_empty_zip(self, client):
        import zipfile, io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            pass  # Empty zip
        buf.seek(0)
        r = await client.post(
            "/api/backup/restore",
            files={"file": ("empty.zip", buf, "application/zip")},
        )
        assert r.status_code == 400  # No bench.db


class TestFrontendEdgeCases:
    """Test frontend serving and static files."""

    @pytest.mark.asyncio
    async def test_html_contains_app_title(self, client):
        r = await client.get("/")
        assert r.status_code == 200
        assert "vLLM Benchmark" in r.text

    @pytest.mark.asyncio
    async def test_html_contains_alpine_import(self, client):
        r = await client.get("/")
        assert "alpine" in r.text.lower()

    @pytest.mark.asyncio
    async def test_html_contains_chart_import(self, client):
        r = await client.get("/")
        assert "chart" in r.text.lower()

    @pytest.mark.asyncio
    async def test_html_has_5_tabs(self, client):
        r = await client.get("/")
        text = r.text
        assert "Servers" in text
        assert "Benchmark" in text
        assert "History" in text
        assert "Compare" in text
        assert "Backup" in text

    @pytest.mark.asyncio
    async def test_css_has_color_variables(self, client):
        r = await client.get("/static/style.css")
        assert r.status_code == 200
        assert "--accent" in r.text

    @pytest.mark.asyncio
    async def test_js_has_app_function(self, client):
        r = await client.get("/static/app.js")
        assert r.status_code == 200
        assert "function createApp()" in r.text
        assert "Alpine.data" in r.text


class TestDBEdgeCases:
    """Edge cases for database layer."""

    @pytest.mark.asyncio
    async def test_run_update_partial_fields(self, db):
        from core.db import run_create, run_update_status, run_get
        await run_create(db, "partial", "srv", "m", "{}")
        await run_update_status(db, "partial", "done", peak_tok_s=999.0)
        r = await run_get(db, "partial")
        assert r["status"] == "done"
        assert r["peak_tok_s"] == 999.0
        assert r["peak_concurrency"] is None  # Not set

    @pytest.mark.asyncio
    async def test_server_update_ignores_unknown_fields(self, db):
        from core.db import server_create, server_update, server_get
        await server_create(db, alias="ign", host="1.1.1.1", port=8000)
        await server_update(db, "ign", unknown_field="x", host="2.2.2.2")
        s = await server_get(db, "ign")
        assert s["host"] == "2.2.2.2"

    @pytest.mark.asyncio
    async def test_setting_overwrite(self, db):
        from core.db import setting_set, setting_get
        await setting_set(db, "x", "1")
        await setting_set(db, "x", "2")
        assert await setting_get(db, "x") == "2"

    @pytest.mark.asyncio
    async def test_init_db_idempotent(self):
        """Calling init_db twice on same path should not fail."""
        tmp = tempfile.mktemp(suffix=".db")
        db1 = await init_db(tmp)
        await db1.close()
        db2 = await init_db(tmp)
        await db2.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass
