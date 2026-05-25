"""Comprehensive tests for vLLM Benchmark GUI."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Ensure project root is on path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import aiosqlite
from httpx import ASGITransport, AsyncClient

from core.db import init_db, DB_PATH
from main import create_app


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    """Fresh in-memory DB for each test."""
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
    """HTTP test client with patched DB."""
    app = create_app()

    # Patch DBMiddleware to use our test DB
    from main import DBMiddleware

    class TestDBMiddleware(DBMiddleware):
        async def dispatch(self, request, call_next):
            request.state.db = db
            try:
                return await call_next(request)
            finally:
                pass  # Don't close the shared test DB

    # Replace middleware
    app.user_middleware = []
    app.add_middleware(TestDBMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── DB Layer Tests ────────────────────────────────────────────────────────────

class TestDatabase:
    """Test all DB CRUD operations."""

    @pytest.mark.asyncio
    async def test_server_create(self, db):
        from core.db import server_create, server_get
        s = await server_create(db, alias="test-srv", host="1.2.3.4", port=8000)
        assert s["alias"] == "test-srv"
        assert s["host"] == "1.2.3.4"
        assert s["port"] == 8000
        assert s["color"] is not None  # Auto-assigned

    @pytest.mark.asyncio
    async def test_server_create_duplicate(self, db):
        from core.db import server_create
        await server_create(db, alias="dup", host="1.1.1.1", port=8000)
        with pytest.raises(Exception):  # UNIQUE constraint
            await server_create(db, alias="dup", host="2.2.2.2", port=8000)

    @pytest.mark.asyncio
    async def test_server_get_not_found(self, db):
        from core.db import server_get
        assert await server_get(db, "nonexistent") is None

    @pytest.mark.asyncio
    async def test_server_list(self, db):
        from core.db import server_create, server_list
        await server_create(db, alias="a", host="1.1.1.1", port=8000)
        await server_create(db, alias="b", host="2.2.2.2", port=8001)
        servers = await server_list(db)
        assert len(servers) == 2
        aliases = {s["alias"] for s in servers}
        assert aliases == {"a", "b"}

    @pytest.mark.asyncio
    async def test_server_update(self, db):
        from core.db import server_create, server_update, server_get
        await server_create(db, alias="upd", host="1.1.1.1", port=8000)
        updated = await server_update(db, "upd", host="9.9.9.9", port=9999)
        assert updated["host"] == "9.9.9.9"
        assert updated["port"] == 9999
        # Original color/tags preserved
        assert updated["alias"] == "upd"

    @pytest.mark.asyncio
    async def test_server_update_noop(self, db):
        from core.db import server_create, server_update
        await server_create(db, alias="noop", host="1.1.1.1", port=8000)
        result = await server_update(db, "noop")  # No fields
        assert result["alias"] == "noop"

    @pytest.mark.asyncio
    async def test_server_delete(self, db):
        from core.db import server_create, server_delete, server_get
        await server_create(db, alias="del", host="1.1.1.1", port=8000)
        assert await server_delete(db, "del") is True
        assert await server_get(db, "del") is None

    @pytest.mark.asyncio
    async def test_server_delete_not_found(self, db):
        from core.db import server_delete
        assert await server_delete(db, "ghost") is False

    @pytest.mark.asyncio
    async def test_server_ping_update(self, db):
        from core.db import server_create, server_ping_update, server_get
        from datetime import datetime
        await server_create(db, alias="ping", host="1.1.1.1", port=8000)
        await server_ping_update(db, "ping", True)
        s = await server_get(db, "ping")
        assert s["last_ping_ok"] == 1
        assert s["last_pinged"] is not None
        # Check timestamp is recent
        dt = datetime.fromisoformat(s["last_pinged"])
        assert (datetime.now() - dt).total_seconds() < 5

    @pytest.mark.asyncio
    async def test_server_run_count(self, db):
        from core.db import server_create, server_run_count, run_create
        await server_create(db, alias="cnt", host="1.1.1.1", port=8000)
        assert await server_run_count(db, "cnt") == 0
        await run_create(db, "r1", "cnt", "model-a", "{}")
        assert await server_run_count(db, "cnt") == 1

    @pytest.mark.asyncio
    async def test_run_create_and_get(self, db):
        from core.db import run_create, run_get
        r = await run_create(db, "uuid-1", "srv", "llama-70b", '{"model":"llama-70b"}')
        assert r["run_id"] == "uuid-1"
        assert r["server_alias"] == "srv"
        assert r["model"] == "llama-70b"
        assert r["status"] == "running"

    @pytest.mark.asyncio
    async def test_run_get_not_found(self, db):
        from core.db import run_get
        assert await run_get(db, "ghost") is None

    @pytest.mark.asyncio
    async def test_run_list(self, db):
        from core.db import run_create, run_list
        await run_create(db, "r1", "srv", "m", "{}")
        await run_create(db, "r2", "srv", "m", "{}")
        runs = await run_list(db, limit=10)
        assert len(runs) == 2

    @pytest.mark.asyncio
    async def test_run_list_filter_by_server(self, db):
        from core.db import run_create, run_list
        await run_create(db, "r1", "srv-a", "m", "{}")
        await run_create(db, "r2", "srv-b", "m", "{}")
        runs = await run_list(db, server_alias="srv-a")
        assert len(runs) == 1
        assert runs[0]["run_id"] == "r1"

    @pytest.mark.asyncio
    async def test_run_list_pagination(self, db):
        from core.db import run_create, run_list
        for i in range(5):
            await run_create(db, f"r{i}", "srv", "m", "{}")
        runs = await run_list(db, limit=2, offset=0)
        assert len(runs) == 2
        runs2 = await run_list(db, limit=2, offset=2)
        assert len(runs2) == 2

    @pytest.mark.asyncio
    async def test_run_update_status(self, db):
        from core.db import run_create, run_update_status, run_get
        await run_create(db, "r1", "srv", "m", "{}")
        await run_update_status(db, "r1", "done", peak_tok_s=1500.5)
        r = await run_get(db, "r1")
        assert r["status"] == "done"
        assert r["peak_tok_s"] == 1500.5

    @pytest.mark.asyncio
    async def test_run_delete(self, db):
        from core.db import run_create, run_delete, run_get
        await run_create(db, "r1", "srv", "m", "{}")
        assert await run_delete(db, "r1") is True
        assert await run_get(db, "r1") is None

    @pytest.mark.asyncio
    async def test_result_create_and_list(self, db):
        from core.db import run_create, result_create, result_list
        await run_create(db, "r1", "srv", "m", "{}")
        await result_create(db, "r1", "medium", 4, throughput_tok_s=1200.5)
        results = await result_list(db, "r1")
        assert len(results) == 1
        assert results[0]["throughput_tok_s"] == 1200.5
        assert results[0]["prompt_key"] == "medium"
        assert results[0]["concurrency"] == 4

    @pytest.mark.asyncio
    async def test_setting_get_set(self, db):
        from core.db import setting_set, setting_get
        assert await setting_get(db, "foo", "bar") == "bar"
        await setting_set(db, "foo", "baz")
        assert await setting_get(db, "foo") == "baz"

    @pytest.mark.asyncio
    async def test_setting_list(self, db):
        from core.db import setting_set, setting_list
        await setting_set(db, "k1", "v1")
        await setting_set(db, "k2", "v2")
        s = await setting_list(db)
        assert s == {"k1": "v1", "k2": "v2"}

    @pytest.mark.asyncio
    async def test_setting_delete(self, db):
        from core.db import setting_set, setting_delete, setting_get
        await setting_set(db, "temp", "val")
        assert await setting_delete(db, "temp") is True
        assert await setting_get(db, "temp") is None

    @pytest.mark.asyncio
    async def test_assign_server_color(self, db):
        from core.db import server_create, assign_server_color
        c1 = await assign_server_color(db)
        assert c1.startswith("#")
        await server_create(db, alias="s1", host="1.1.1.1", port=8000, color=c1)
        c2 = await assign_server_color(db)
        assert c2 != c1  # Should pick different color

    @pytest.mark.asyncio
    async def test_result_delete_for_run(self, db):
        from core.db import run_create, result_create, result_list, result_delete_for_run
        await run_create(db, "r1", "srv", "m", "{}")
        await result_create(db, "r1", "short", 1)
        await result_create(db, "r1", "medium", 2)
        assert len(await result_list(db, "r1")) == 2
        await result_delete_for_run(db, "r1")
        assert len(await result_list(db, "r1")) == 0


# ── Model Validation Tests ────────────────────────────────────────────────────

class TestModels:
    """Test Pydantic model validation."""

    def test_server_profile_create_valid(self):
        from core.models import ServerProfileCreate
        s = ServerProfileCreate(alias="my-srv", host="1.2.3.4", port=8000)
        assert s.alias == "my-srv"
        assert s.description is None

    def test_server_profile_create_invalid_alias_spaces(self):
        from core.models import ServerProfileCreate
        with pytest.raises(Exception):
            ServerProfileCreate(alias="my srv", host="1.2.3.4", port=8000)

    def test_server_profile_create_invalid_port(self):
        from core.models import ServerProfileCreate
        with pytest.raises(Exception):
            ServerProfileCreate(alias="s", host="h", port=0)

    def test_server_profile_update_partial(self):
        from core.models import ServerProfileUpdate
        u = ServerProfileUpdate(host="9.9.9.9")
        assert u.port is None
        assert u.host == "9.9.9.9"

    def test_ping_result(self):
        from core.models import PingResult
        p = PingResult(ok=True, model_count=2, latency_ms=15.3)
        assert p.ok is True
        assert p.error is None

    def test_benchmark_config_valid(self):
        from core.models import BenchmarkConfig
        c = BenchmarkConfig(
            server_alias="srv",
            model="llama",
            concurrency_levels=[1, 2, 4],
            prompt_keys=["short", "medium"],
        )
        assert c.num_requests == 8
        assert c.temperature == 0.0
        assert c.quick_mode is False

    def test_benchmark_config_custom_prompts(self):
        from core.models import BenchmarkConfig
        c = BenchmarkConfig(
            server_alias="srv",
            model="llama",
            concurrency_levels=[1],
            prompt_keys=["custom"],
            custom_prompts={"custom": {"prompt": "hello", "max_tokens": 100}},
        )
        assert c.custom_prompts["custom"]["prompt"] == "hello"

    def test_progress_event(self):
        from core.models import ProgressEvent
        e = ProgressEvent(prompt_key="medium", concurrency=4, done=5, total=8, tok_s=1200.0)
        assert e.done == 5

    def test_result_event(self):
        from core.models import ResultEvent
        e = ResultEvent(
            prompt_key="short", concurrency=1,
            throughput_tok_s=300.0, avg_latency_ms=150.0,
            p50_latency_ms=140.0, p95_latency_ms=180.0,
            avg_ttft_ms=40.0, success_count=5, total_count=5,
        )
        assert e.throughput_tok_s == 300.0

    def test_done_event(self):
        from core.models import DoneEvent
        e = DoneEvent(run_id="abc", peak_tok_s=2104.5)
        assert e.peak_tok_s == 2104.5

    def test_error_event(self):
        from core.models import ErrorEvent
        e = ErrorEvent(message="Connection refused")
        assert e.message == "Connection refused"

    def test_server_test_request(self):
        from core.models import ServerTestRequest
        r = ServerTestRequest(host="1.2.3.4", port=8080)
        assert r.host == "1.2.3.4"

    def test_compare_row(self):
        from core.models import CompareRow
        r = CompareRow(concurrency=4, value_a=1200.0, value_b=1100.0, delta=100.0, delta_pct=9.1)
        assert r.delta_pct == 9.1


# ── Benchmark Engine Tests ───────────────────────────────────────────────────

class TestBenchmarkEngine:
    """Test benchmark engine functions (mocked network)."""

    @pytest.mark.asyncio
    async def test_ping_server_unreachable(self):
        from core import benchmark
        result = await benchmark.ping_server("http://127.0.0.1:19999")
        assert result["ok"] is False
        assert result["model_count"] == 0

    @pytest.mark.asyncio
    async def test_ping_server_invalid_url(self):
        from core import benchmark
        result = await benchmark.ping_server("http://not-a-real-host.invalid:9999")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_get_models_empty_on_error(self):
        from core import benchmark
        models = await benchmark.get_models("http://127.0.0.1:19999")
        assert models == []

    @pytest.mark.asyncio
    async def test_prompts_defined(self):
        from core import benchmark
        assert "short" in benchmark.PROMPTS
        assert "medium" in benchmark.PROMPTS
        assert "long" in benchmark.PROMPTS
        assert "coding" in benchmark.PROMPTS
        assert "custom" in benchmark.PROMPTS
        for key, val in benchmark.PROMPTS.items():
            assert "prompt" in val
            assert "max_tokens" in val
            assert "label" in val

    @pytest.mark.asyncio
    async def test_prompt_level_result_empty(self):
        from core.benchmark import PromptLevelResult
        r = PromptLevelResult(prompt_key="medium", concurrency=4)
        assert r.throughput_tok_s == 0.0
        assert r.avg_latency_ms == 0.0
        assert r.p50_latency_ms == 0.0
        assert r.p95_latency_ms == 0.0
        assert r.avg_ttft_ms == 0.0
        assert r.successful == []
        assert r.failed == []

    @pytest.mark.asyncio
    async def test_prompt_level_result_with_data(self):
        from core.benchmark import PromptLevelResult, RequestResult
        r = PromptLevelResult(prompt_key="short", concurrency=1, total_time_s=2.0)
        r.results = [
            RequestResult(completion_tokens=100, latency_ms=500, ttft_ms=50, success=True),
            RequestResult(completion_tokens=120, latency_ms=600, ttft_ms=60, success=True),
            RequestResult(completion_tokens=0, latency_ms=0, ttft_ms=0, success=False, error="timeout"),
        ]
        assert len(r.successful) == 2
        assert len(r.failed) == 1
        assert r.throughput_tok_s == (100 + 120) / 2.0  # 110.0
        assert r.avg_latency_ms == 550.0
        assert r.avg_ttft_ms == 55.0


# ── API Route Tests ──────────────────────────────────────────────────────────

class TestAPIServers:
    """Test server management API endpoints."""

    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        r = await client.get("/api/servers")
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_create_server(self, client):
        r = await client.post("/api/servers", json={
            "alias": "gpu-box",
            "host": "192.168.1.22",
            "port": 8018,
            "description": "NVIDIA GB10",
            "tags": "local, blackwell",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["alias"] == "gpu-box"
        assert data["color"] is not None

    @pytest.mark.asyncio
    async def test_create_server_duplicate(self, client):
        await client.post("/api/servers", json={"alias": "dup", "host": "1.1.1.1", "port": 8000})
        r = await client.post("/api/servers", json={"alias": "dup", "host": "2.2.2.2", "port": 8000})
        assert r.status_code == 409

    @pytest.mark.asyncio
    async def test_update_server(self, client):
        await client.post("/api/servers", json={"alias": "upd", "host": "1.1.1.1", "port": 8000})
        r = await client.put("/api/servers/upd", json={"host": "9.9.9.9", "port": 9999})
        assert r.status_code == 200
        assert r.json()["host"] == "9.9.9.9"

    @pytest.mark.asyncio
    async def test_update_server_not_found(self, client):
        r = await client.put("/api/servers/ghost", json={"host": "1.1.1.1"})
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_server(self, client):
        await client.post("/api/servers", json={"alias": "del", "host": "1.1.1.1", "port": 8000})
        r = await client.delete("/api/servers/del")
        assert r.status_code == 200
        assert r.json()["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_server_not_found(self, client):
        r = await client.delete("/api/servers/ghost")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_test_connection(self, client):
        r = await client.post("/api/servers/test", json={"host": "127.0.0.1", "port": 19999})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False  # Nothing listening there

    @pytest.mark.asyncio
    async def test_ping_server_not_found(self, client):
        r = await client.get("/api/servers/ghost/ping")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_get_models_not_found(self, client):
        r = await client.get("/api/servers/ghost/models")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_server_with_run_count(self, client):
        await client.post("/api/servers", json={"alias": "s1", "host": "1.1.1.1", "port": 8000})
        r = await client.get("/api/servers")
        assert r.status_code == 200
        servers = r.json()
        assert len(servers) == 1
        assert "run_count" in servers[0]


class TestAPIResults:
    """Test results query and compare API."""

    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        r = await client.get("/api/results")
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_get_run_not_found(self, client):
        r = await client.get("/api/results/nonexistent")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_run_not_found(self, client):
        r = await client.delete("/api/results/nonexistent")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_export_not_found(self, client):
        r = await client.get("/api/results/nonexistent/export")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_compare_missing_params(self, client):
        r = await client.get("/api/results/compare")
        assert r.status_code == 422  # Missing required query params

    @pytest.mark.asyncio
    async def test_compare_not_found_runs(self, client):
        r = await client.get("/api/results/compare?run_a_id=x&run_b_id=y")
        assert r.status_code == 404


class TestAPIBackup:
    """Test backup API endpoints."""

    @pytest.mark.asyncio
    async def test_create_backup(self, client):
        r = await client.post("/api/backup/create")
        assert r.status_code == 200
        data = r.json()
        assert "filename" in data
        assert "size_bytes" in data
        assert data["size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_list_backups(self, client):
        await client.post("/api/backup/create")
        r = await client.get("/api/backup/list")
        assert r.status_code == 200
        backups = r.json()
        assert len(backups) >= 1
        assert "filename" in backups[0]
        assert "size_bytes" in backups[0]

    @pytest.mark.asyncio
    async def test_download_backup(self, client):
        create_resp = await client.post("/api/backup/create")
        filename = create_resp.json()["filename"]
        r = await client.get(f"/api/backup/{filename}")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"

    @pytest.mark.asyncio
    async def test_download_backup_not_found(self, client):
        r = await client.get("/api/backup/nonexistent.zip")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_backup(self, client):
        create_resp = await client.post("/api/backup/create")
        filename = create_resp.json()["filename"]
        r = await client.delete(f"/api/backup/{filename}")
        assert r.status_code == 200
        assert r.json()["deleted"] is True
        # Verify deleted
        r2 = await client.get(f"/api/backup/{filename}")
        assert r2.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_backup_not_found(self, client):
        r = await client.delete("/api/backup/nonexistent.zip")
        assert r.status_code == 404


class TestAPIBenchmark:
    """Test benchmark API endpoints."""

    @pytest.mark.asyncio
    async def test_start_no_server(self, client):
        r = await client.post("/api/benchmark/start", json={
            "server_alias": "nonexistent",
            "model": "llama",
            "concurrency_levels": [1],
            "prompt_keys": ["short"],
        })
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_start_with_server(self, client):
        # Create a server first
        await client.post("/api/servers", json={"alias": "bench-srv", "host": "127.0.0.1", "port": 19999})
        r = await client.post("/api/benchmark/start", json={
            "server_alias": "bench-srv",
            "model": "test-model",
            "concurrency_levels": [1],
            "prompt_keys": ["short"],
            "num_requests": 1,
        })
        assert r.status_code == 200
        data = r.json()
        assert "run_id" in data

    @pytest.mark.asyncio
    async def test_stop_nonexistent(self, client):
        r = await client.post("/api/benchmark/fake-id/stop", json={})
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_stream_nonexistent(self, client):
        r = await client.get("/api/benchmark/fake-id/stream")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_status_nonexistent(self, client):
        r = await client.get("/api/benchmark/fake-id/status")
        assert r.status_code == 404


class TestAPIMain:
    """Test basic app serving."""

    @pytest.mark.asyncio
    async def test_serves_html(self, client):
        r = await client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "vLLM Benchmark" in r.text

    @pytest.mark.asyncio
    async def test_serves_static_css(self, client):
        r = await client.get("/static/style.css")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_serves_static_js(self, client):
        r = await client.get("/static/app.js")
        assert r.status_code == 200
