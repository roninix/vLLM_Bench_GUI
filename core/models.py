"""Pydantic v2 models for request/response validation."""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ── Server profile ────────────────────────────────────────────────────────────

class ServerProfileCreate(BaseModel):
    alias: str = Field(..., min_length=1, max_length=64, pattern=r"^[^\s]+$")
    host: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)
    description: Optional[str] = None
    color: Optional[str] = None
    tags: Optional[str] = None


class ServerProfileUpdate(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    description: Optional[str] = None
    color: Optional[str] = None
    tags: Optional[str] = None


class ServerProfile(BaseModel):
    id: int
    alias: str
    host: str
    port: int
    description: Optional[str] = None
    color: Optional[str] = None
    tags: Optional[str] = None
    created_at: str
    last_pinged: Optional[str] = None
    last_ping_ok: Optional[int] = None


class PingResult(BaseModel):
    ok: bool
    model_count: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None


class ServerTestRequest(BaseModel):
    host: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)


# ── Benchmark config ─────────────────────────────────────────────────────────

class BenchmarkConfig(BaseModel):
    server_alias: str
    model: str
    concurrency_levels: list[int] = Field(..., min_length=1)
    prompt_keys: list[str] = Field(..., min_length=1)
    num_requests: int = Field(default=8, ge=1, le=100)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    quick_mode: bool = False
    custom_prompts: dict[str, dict] = Field(default_factory=dict)
    # custom_prompts e.g. {"custom": {"prompt": "...", "max_tokens": 256}}


class BenchmarkStartResponse(BaseModel):
    run_id: str


# ── Progress event (internal, not a request model) ───────────────────────────

class ProgressEvent(BaseModel):
    prompt_key: str
    concurrency: int
    done: int = 0
    total: int = 0
    tok_s: float = 0.0


class ResultEvent(BaseModel):
    prompt_key: str
    concurrency: int
    throughput_tok_s: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    avg_ttft_ms: float
    success_count: int
    total_count: int


class DoneEvent(BaseModel):
    run_id: str
    peak_tok_s: float


class ErrorEvent(BaseModel):
    message: str


# ── Run result row ───────────────────────────────────────────────────────────

class RunResultRow(BaseModel):
    id: int
    run_id: str
    prompt_key: str
    concurrency: int
    throughput_tok_s: Optional[float] = None
    avg_latency_ms: Optional[float] = None
    p50_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    avg_ttft_ms: Optional[float] = None
    total_time_s: Optional[float] = None
    success_count: Optional[int] = None
    total_count: Optional[int] = None
    raw_json: Optional[str] = None


class BenchmarkRunDetail(BaseModel):
    id: int
    run_id: str
    server_alias: str
    model: str
    timestamp: str
    config_json: str
    peak_tok_s: Optional[float] = None
    peak_concurrency: Optional[int] = None
    total_requests: Optional[int] = None
    success_requests: Optional[int] = None
    status: str
    created_at: str
    results: list[RunResultRow] = Field(default_factory=list)


# ── Compare / delta ──────────────────────────────────────────────────────────

class CompareRow(BaseModel):
    concurrency: int
    value_a: Optional[float] = None
    value_b: Optional[float] = None
    delta: Optional[float] = None
    delta_pct: Optional[float] = None


class CompareResponse(BaseModel):
    prompt_key: str
    metric: str
    run_a_id: str
    run_b_id: str
    server_a_alias: str
    server_b_alias: str
    rows: list[CompareRow]
