"""Async benchmark engine — ported from vllm_benchmark.py with progress callbacks."""

from __future__ import annotations
import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable

import aiohttp

from core.models import BenchmarkConfig, ProgressEvent, ResultEvent


# ── Prompt library ────────────────────────────────────────────────────────────

PROMPTS = {
    "short": {
        "prompt": "What is 2+2? Answer in one sentence.",
        "max_tokens": 50,
        "label": "Short (~50 tok)",
    },
    "medium": {
        "prompt": (
            "Explain the difference between TCP and UDP networking protocols. "
            "Include key characteristics, use cases, and trade-offs."
        ),
        "max_tokens": 512,
        "label": "Medium (~512 tok)",
    },
    "long": {
        "prompt": (
            "Write a comprehensive technical analysis of MoE (Mixture of Experts) "
            "architecture in large language models. Cover: what it is, how routing works, "
            "why it's efficient, key implementations (Switch Transformer, Mixtral, etc.), "
            "training challenges, and inference optimization techniques."
        ),
        "max_tokens": 2048,
        "label": "Long (~2K tok)",
    },
    "coding": {
        "prompt": (
            "Write a Python implementation of a binary search tree with "
            "insert, search, delete, and in-order traversal methods. "
            "Include proper error handling and docstrings."
        ),
        "max_tokens": 1024,
        "label": "Code (~1K tok)",
    },
    "custom": {
        "prompt": "",
        "max_tokens": 256,
        "label": "Custom",
    },
}


# ── Internal data classes ─────────────────────────────────────────────────────

@dataclass
class RequestResult:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    ttft_ms: float = 0.0
    success: bool = True
    error: str = ""


@dataclass
class PromptLevelResult:
    prompt_key: str
    concurrency: int
    results: list[RequestResult] = field(default_factory=list)
    total_time_s: float = 0.0

    @property
    def successful(self) -> list[RequestResult]:
        return [r for r in self.results if r.success]

    @property
    def failed(self) -> list[RequestResult]:
        return [r for r in self.results if not r.success]

    @property
    def throughput_tok_s(self) -> float:
        if not self.successful or self.total_time_s == 0:
            return 0.0
        total_tokens = sum(r.completion_tokens for r in self.successful)
        return total_tokens / self.total_time_s

    @property
    def avg_latency_ms(self) -> float:
        if not self.successful:
            return 0.0
        return statistics.mean(r.latency_ms for r in self.successful)

    @property
    def p50_latency_ms(self) -> float:
        if not self.successful:
            return 0.0
        return statistics.median(r.latency_ms for r in self.successful)

    @property
    def p95_latency_ms(self) -> float:
        if not self.successful:
            return 0.0
        sorted_l = sorted(r.latency_ms for r in self.successful)
        idx = int(len(sorted_l) * 0.95)
        return sorted_l[min(idx, len(sorted_l) - 1)]

    @property
    def avg_ttft_ms(self) -> float:
        if not self.successful:
            return 0.0
        ttfts = [r.ttft_ms for r in self.successful if r.ttft_ms > 0]
        return statistics.mean(ttfts) if ttfts else 0.0


# ── Single request call ──────────────────────────────────────────────────────

async def _call_vllm(
    session: aiohttp.ClientSession,
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float = 0.0,
    timeout_s: int = 300,
) -> RequestResult:
    result = RequestResult()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    t_start = time.perf_counter()
    first_token_time = None

    try:
        async with session.post(
            f"{base_url}/v1/chat/completions",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                result.success = False
                result.error = f"HTTP {resp.status}: {body[:200]}"
                return result

            completion_text = ""
            async for line in resp.content:
                line = line.decode("utf-8").strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:])
                        choices = chunk.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta", {})
                            token_text = delta.get("content", "") or delta.get("reasoning", "")
                            if token_text and first_token_time is None:
                                first_token_time = time.perf_counter()
                            completion_text += token_text

                        usage = chunk.get("usage")
                        if usage:
                            result.prompt_tokens = usage.get("prompt_tokens", 0)
                            result.completion_tokens = usage.get("completion_tokens", 0)
                            result.total_tokens = usage.get("total_tokens", 0)
                    except json.JSONDecodeError:
                        pass

        t_end = time.perf_counter()
        result.latency_ms = (t_end - t_start) * 1000
        if first_token_time:
            result.ttft_ms = (first_token_time - t_start) * 1000

        # Fallback token count
        if result.completion_tokens == 0 and completion_text:
            result.completion_tokens = len(completion_text.split())

    except asyncio.TimeoutError:
        result.success = False
        result.error = "Timeout"
    except Exception as e:
        result.success = False
        result.error = str(e)

    return result


# ── Public API ────────────────────────────────────────────────────────────────

async def get_models(base_url: str) -> list[str]:
    """Fetch model list from vLLM /v1/models endpoint."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url}/v1/models",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = data.get("data", [])
                    return [m.get("id", "unknown") for m in models]
    except Exception:
        pass
    return []


async def ping_server(base_url: str) -> dict:
    """Ping the vLLM server and return reachability info."""
    try:
        t_start = time.perf_counter()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url}/v1/models",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                latency_ms = (time.perf_counter() - t_start) * 1000
                if resp.status == 200:
                    data = await resp.json()
                    models = data.get("data", [])
                    return {
                        "ok": True,
                        "model_count": len(models),
                        "latency_ms": round(latency_ms, 1),
                        "error": None,
                    }
                else:
                    body = await resp.text()
                    return {
                        "ok": False,
                        "model_count": 0,
                        "latency_ms": round(latency_ms, 1),
                        "error": f"HTTP {resp.status}: {body[:200]}",
                    }
    except asyncio.TimeoutError:
        return {"ok": False, "model_count": 0, "latency_ms": 0, "error": "Timeout"}
    except Exception as e:
        return {"ok": False, "model_count": 0, "latency_ms": 0, "error": str(e)}


async def run_benchmark(
    config: BenchmarkConfig,
    base_url: str,
    progress_cb: Callable[[dict], Awaitable[None]],
    stop_event: asyncio.Event,
    timeout_s: int = 300,
) -> dict:
    """
    Run the full benchmark suite per config.
    Yields progress via `progress_cb` and respects `stop_event`.
    Returns aggregated summary dict.
    """
    all_results: list[PromptLevelResult] = []
    peak_tok_s = 0.0
    peak_concurrency = 0
    total_requests_count = 0
    success_requests_count = 0

    for prompt_key in config.prompt_keys:
        prompt_cfg = PROMPTS.get(prompt_key, PROMPTS["custom"])
        # Merge custom prompt overrides
        if prompt_key == "custom" and config.custom_prompts.get("custom"):
            custom = config.custom_prompts["custom"]
            prompt_cfg = {
                "prompt": custom.get("prompt", prompt_cfg["prompt"]),
                "max_tokens": custom.get("max_tokens", prompt_cfg["max_tokens"]),
                "label": custom.get("label", prompt_cfg["label"]),
            }

        for concurrency in config.concurrency_levels:
            # Check stop
            if stop_event.is_set():
                break

            num_requests = config.num_requests

            # Progress event: starting level
            await progress_cb({
                "event": "progress",
                "data": {
                    "prompt_key": prompt_key,
                    "concurrency": concurrency,
                    "done": 0,
                    "total": num_requests,
                    "tok_s": 0.0,
                },
            })

            connector = aiohttp.TCPConnector(limit=concurrency + 4)
            async with aiohttp.ClientSession(connector=connector) as session:
                semaphore = asyncio.Semaphore(concurrency)

                async def bounded_call():
                    async with semaphore:
                        return await _call_vllm(
                            session,
                            base_url,
                            config.model,
                            prompt_cfg["prompt"],
                            prompt_cfg["max_tokens"],
                            config.temperature,
                            timeout_s,
                        )

                t_start = time.perf_counter()
                tasks = [bounded_call() for _ in range(num_requests)]
                results = await asyncio.gather(*tasks)
                t_end = time.perf_counter()

            level_result = PromptLevelResult(
                prompt_key=prompt_key,
                concurrency=concurrency,
                results=list(results),
                total_time_s=t_end - t_start,
            )
            all_results.append(level_result)

            total_requests_count += len(results)
            success_requests_count += len(level_result.successful)

            tps = level_result.throughput_tok_s
            if tps > peak_tok_s:
                peak_tok_s = tps
            if concurrency > peak_concurrency:
                peak_concurrency = concurrency

            # Result event
            await progress_cb({
                "event": "result",
                "data": {
                    "prompt_key": prompt_key,
                    "concurrency": concurrency,
                    "throughput_tok_s": round(tps, 1),
                    "avg_latency_ms": round(level_result.avg_latency_ms, 1),
                    "p50_latency_ms": round(level_result.p50_latency_ms, 1),
                    "p95_latency_ms": round(level_result.p95_latency_ms, 1),
                    "avg_ttft_ms": round(level_result.avg_ttft_ms, 1),
                    "success_count": len(level_result.successful),
                    "total_count": len(results),
                },
            })

            # Update progress bar to complete
            await progress_cb({
                "event": "progress",
                "data": {
                    "prompt_key": prompt_key,
                    "concurrency": concurrency,
                    "done": num_requests,
                    "total": num_requests,
                    "tok_s": round(tps, 1),
                },
            })

        if stop_event.is_set():
            break

    # Build raw_json per level for DB storage
    raw_results = []
    for lr in all_results:
        raw_results.append({
            "prompt_key": lr.prompt_key,
            "concurrency": lr.concurrency,
            "throughput_tok_s": round(lr.throughput_tok_s, 1),
            "avg_latency_ms": round(lr.avg_latency_ms, 1),
            "p50_latency_ms": round(lr.p50_latency_ms, 1),
            "p95_latency_ms": round(lr.p95_latency_ms, 1),
            "avg_ttft_ms": round(lr.avg_ttft_ms, 1),
            "total_time_s": round(lr.total_time_s, 2),
            "success_count": len(lr.successful),
            "total_count": len(lr.results),
            "request_details": [
                {
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "latency_ms": round(r.latency_ms, 1),
                    "ttft_ms": round(r.ttft_ms, 1),
                    "success": r.success,
                    "error": r.error,
                }
                for r in lr.results
            ],
        })

    return {
        "peak_tok_s": round(peak_tok_s, 1),
        "peak_concurrency": peak_concurrency,
        "total_requests": total_requests_count,
        "success_requests": success_requests_count,
        "level_results": raw_results,
    }
