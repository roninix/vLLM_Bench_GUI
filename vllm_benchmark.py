#!/usr/bin/env python3
"""
vLLM Throughput Benchmark
─────────────────────────
Tek ve concurrent request'lerde token/sn ölçümü.

Kullanım:
  python3 vllm_benchmark.py                    # varsayılan: castleai
  python3 vllm_benchmark.py --host 192.168.1.22 --port 8018
  python3 vllm_benchmark.py --quick            # hızlı test (daha az round)
  python3 vllm_benchmark.py --concurrency 1 4 8 12  # özel concurrency seviyeleri
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

try:
    import aiohttp
except ImportError:
    print("aiohttp gerekli: pip install aiohttp --break-system-packages")
    sys.exit(1)

# ── ANSI renk kodları ──────────────────────────────────────────────────────────
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"
    GRAY   = "\033[90m"

# ── Test prompts ───────────────────────────────────────────────────────────────
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
}

MAX_CONCURRENCY = 12

# ── Veri yapıları ─────────────────────────────────────────────────────────────
@dataclass
class RequestResult:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    ttft_ms: float = 0.0      # Time to first token
    success: bool = True
    error: str = ""

@dataclass
class BenchmarkResult:
    test_name: str
    concurrency: int
    prompt_label: str
    results: List[RequestResult] = field(default_factory=list)
    total_time_s: float = 0.0

    @property
    def successful(self):
        return [r for r in self.results if r.success]

    @property
    def failed(self):
        return [r for r in self.results if not r.success]

    @property
    def throughput_tok_s(self):
        if not self.successful or self.total_time_s == 0:
            return 0
        total_tokens = sum(r.completion_tokens for r in self.successful)
        return total_tokens / self.total_time_s

    @property
    def avg_latency_ms(self):
        if not self.successful:
            return 0
        return statistics.mean(r.latency_ms for r in self.successful)

    @property
    def p50_latency_ms(self):
        if not self.successful:
            return 0
        return statistics.median(r.latency_ms for r in self.successful)

    @property
    def p95_latency_ms(self):
        if not self.successful:
            return 0
        sorted_l = sorted(r.latency_ms for r in self.successful)
        idx = int(len(sorted_l) * 0.95)
        return sorted_l[min(idx, len(sorted_l) - 1)]

    @property
    def avg_ttft_ms(self):
        if not self.successful:
            return 0
        ttfts = [r.ttft_ms for r in self.successful if r.ttft_ms > 0]
        return statistics.mean(ttfts) if ttfts else 0

    @property
    def total_completion_tokens(self):
        return sum(r.completion_tokens for r in self.successful)

    @property
    def avg_completion_tokens(self):
        if not self.successful:
            return 0
        return self.total_completion_tokens / len(self.successful)


# ── API çağrısı ───────────────────────────────────────────────────────────────
async def call_vllm(
    session: aiohttp.ClientSession,
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> RequestResult:
    result = RequestResult()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    t_start = time.perf_counter()
    first_token_time = None

    try:
        async with session.post(
            f"{base_url}/v1/chat/completions",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=300),
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
                            # Bazı modeller reasoning token'larını ayrı alanda döndürüyor.
                            token_text = delta.get("content", "") or delta.get("reasoning", "")
                            if token_text and first_token_time is None:
                                first_token_time = time.perf_counter()
                            completion_text += token_text

                        # usage bilgisi (son chunk'ta)
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

        # usage stream'de gelmezse token sayısını tahmin et
        if result.completion_tokens == 0 and completion_text:
            result.completion_tokens = len(completion_text.split())

    except asyncio.TimeoutError:
        result.success = False
        result.error = "Timeout (300s)"
    except Exception as e:
        result.success = False
        result.error = str(e)

    return result


# ── Model bilgisi al ──────────────────────────────────────────────────────────
async def get_model_info(base_url: str) -> Optional[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url}/v1/models",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = data.get("data", [])
                    if models:
                        return models[0].get("id", "unknown")
    except Exception:
        pass
    return None


# ── Tek test çalıştır ─────────────────────────────────────────────────────────
async def run_benchmark(
    base_url: str,
    model: str,
    prompt_key: str,
    concurrency: int,
    num_requests: int,
) -> BenchmarkResult:
    prompt_cfg = PROMPTS[prompt_key]
    result = BenchmarkResult(
        test_name=f"c{concurrency}_{prompt_key}",
        concurrency=concurrency,
        prompt_label=prompt_cfg["label"],
    )

    connector = aiohttp.TCPConnector(limit=concurrency + 4)
    async with aiohttp.ClientSession(connector=connector) as session:
        semaphore = asyncio.Semaphore(concurrency)

        async def bounded_call():
            async with semaphore:
                return await call_vllm(
                    session,
                    base_url,
                    model,
                    prompt_cfg["prompt"],
                    prompt_cfg["max_tokens"],
                )

        t_start = time.perf_counter()
        tasks = [bounded_call() for _ in range(num_requests)]
        results = await asyncio.gather(*tasks)
        t_end = time.perf_counter()

    result.results = list(results)
    result.total_time_s = t_end - t_start
    return result


# ── Çıktı formatları ──────────────────────────────────────────────────────────
def print_header(base_url: str, model: str):
    print(f"\n{C.BOLD}{C.CYAN}{'═' * 72}{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ⚡ vLLM THROUGHPUT BENCHMARK{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'═' * 72}{C.RESET}")
    print(f"  {C.GRAY}Host  :{C.RESET} {base_url}")
    print(f"  {C.GRAY}Model :{C.RESET} {model}")
    print(f"  {C.GRAY}Time  :{C.RESET} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{C.BOLD}{C.CYAN}{'─' * 72}{C.RESET}\n")


def throughput_bar(tps: float, max_tps: float, width: int = 24) -> str:
    if max_tps == 0:
        return " " * width
    ratio = min(tps / max_tps, 1.0)
    filled = int(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    if ratio > 0.7:
        color = C.GREEN
    elif ratio > 0.4:
        color = C.YELLOW
    else:
        color = C.RED
    return f"{color}{bar}{C.RESET}"


def print_result_row(br: BenchmarkResult, max_tps: float):
    ok = len(br.successful)
    total = len(br.results)
    fail = len(br.failed)
    tps = br.throughput_tok_s
    bar = throughput_bar(tps, max_tps)

    fail_str = f" {C.RED}✗{fail}{C.RESET}" if fail > 0 else ""
    ttft_str = f"{br.avg_ttft_ms:6.0f}ms" if br.avg_ttft_ms > 0 else "   n/a  "

    print(
        f"  {C.BOLD}c={br.concurrency:<3}{C.RESET} "
        f"{br.prompt_label:<16} "
        f"{bar} "
        f"{C.BOLD}{C.WHITE}{tps:7.1f}{C.RESET} tok/s  "
        f"lat {C.YELLOW}{br.avg_latency_ms/1000:5.1f}s{C.RESET}  "
        f"p95 {br.p95_latency_ms/1000:5.1f}s  "
        f"ttft {ttft_str}  "
        f"{C.GRAY}({ok}/{total}){C.RESET}{fail_str}"
    )
    if fail > 0 and br.failed:
        err = br.failed[0].error or "bilinmeyen hata"
        if len(err) > 140:
            err = err[:137] + "..."
        print(f"      {C.DIM}{C.RED}→ {err}{C.RESET}")


def print_section(title: str):
    print(f"\n{C.BOLD}{C.BLUE}  ▶ {title}{C.RESET}")
    print(f"  {C.GRAY}{'─' * 68}{C.RESET}")
    print(
        f"  {'':5} {'Prompt':<16} {'Throughput':>26} {'Throughput':>9}  "
        f"{'Avg Lat':>8}  {'P95 Lat':>8}  {'TTFT':>10}  {'OK/N'}"
    )
    print(f"  {C.GRAY}{'─' * 68}{C.RESET}")


def print_summary_table(all_results: List[BenchmarkResult]):
    print(f"\n{C.BOLD}{C.CYAN}{'═' * 72}{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  📊 ÖZET — En Yüksek Throughput{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'─' * 72}{C.RESET}")

    # Prompt tipine göre en iyi sonuç
    by_prompt = {}
    for r in all_results:
        key = r.prompt_label
        if key not in by_prompt or r.throughput_tok_s > by_prompt[key].throughput_tok_s:
            by_prompt[key] = r

    max_tps = max((r.throughput_tok_s for r in by_prompt.values()), default=1)

    print(f"  {'Prompt':<18} {'Best Concurrency':>18} {'Tok/s':>10} {'Bar':>26}")
    print(f"  {C.GRAY}{'─' * 68}{C.RESET}")
    for label, r in sorted(by_prompt.items(), key=lambda x: -x[1].throughput_tok_s):
        bar = throughput_bar(r.throughput_tok_s, max_tps, 20)
        print(
            f"  {label:<18} "
            f"{'c=' + str(r.concurrency):>18} "
            f"{C.BOLD}{C.WHITE}{r.throughput_tok_s:>9.1f}{C.RESET} "
            f" {bar}"
        )

    # Genel peak
    best = max(all_results, key=lambda r: r.throughput_tok_s, default=None)
    if best:
        print(f"\n  {C.GREEN}{C.BOLD}Peak throughput:{C.RESET} "
              f"{C.WHITE}{C.BOLD}{best.throughput_tok_s:.1f} tok/s{C.RESET} "
              f"{C.GRAY}(c={best.concurrency}, {best.prompt_label}){C.RESET}")

    print(f"{C.BOLD}{C.CYAN}{'═' * 72}{C.RESET}\n")


def save_json(
    all_results: List[BenchmarkResult],
    path: str,
    *,
    base_url: str,
    model: str,
    prompt_keys: List[str],
    concurrency_levels: List[int],
    quick_mode: bool,
):
    data = []
    for r in all_results:
        err_samples = []
        seen = set()
        for fr in r.failed:
            e = (fr.error or "").strip()
            if e and e not in seen:
                seen.add(e)
                err_samples.append(e)
                if len(err_samples) >= 3:
                    break
        row = {
            "test_name": r.test_name,
            "concurrency": r.concurrency,
            "prompt_label": r.prompt_label,
            "throughput_tok_s": round(r.throughput_tok_s, 2),
            "avg_latency_ms": round(r.avg_latency_ms, 1),
            "p50_latency_ms": round(r.p50_latency_ms, 1),
            "p95_latency_ms": round(r.p95_latency_ms, 1),
            "avg_ttft_ms": round(r.avg_ttft_ms, 1),
            "total_time_s": round(r.total_time_s, 2),
            "success_count": len(r.successful),
            "total_count": len(r.results),
            "avg_completion_tokens": round(r.avg_completion_tokens, 1),
        }
        if err_samples:
            row["error_samples"] = err_samples
        data.append(row)
    best = max(all_results, key=lambda r: r.throughput_tok_s, default=None)
    summary = {
        "total_tests": len(all_results),
        "total_successful_requests": sum(len(r.successful) for r in all_results),
        "total_requests": sum(len(r.results) for r in all_results),
    }
    if best:
        summary["best_result"] = {
            "test_name": best.test_name,
            "prompt_label": best.prompt_label,
            "concurrency": best.concurrency,
            "throughput_tok_s": round(best.throughput_tok_s, 2),
        }

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "base_url": base_url,
            "model": model,
            "quick_mode": quick_mode,
            "prompt_keys": prompt_keys,
            "concurrency_levels": concurrency_levels,
        },
        "summary": summary,
        "results": data,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"  {C.GRAY}JSON kaydedildi: {path}{C.RESET}")


def default_report_filename() -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{timestamp}.json"


# ── Ana benchmark akışı ───────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="vLLM Throughput Benchmark")
    parser.add_argument("--host", default="192.168.1.22")
    parser.add_argument("--port", default=8018, type=int)
    parser.add_argument("--model", default=None, help="Model ID (auto-detect if not set)")
    parser.add_argument("--quick", action="store_true", help="Hızlı mod (daha az istek)")
    parser.add_argument(
        "--concurrency",
        nargs="+",
        type=int,
        default=None,
        help="Test edilecek concurrency seviyeleri (varsayılan: 1 2 4 8 12, max: 12)",
    )
    parser.add_argument(
        "--json",
        default=None,
        help="Rapor dosya yolu (varsayılan: tarih_saat.json)",
    )
    parser.add_argument(
        "--prompts",
        nargs="+",
        choices=list(PROMPTS.keys()),
        default=None,
        help="Test edilecek prompt tipleri",
    )
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"

    # Model bilgisini al
    print(f"\n{C.GRAY}Bağlanılıyor: {base_url} ...{C.RESET}", end="", flush=True)
    model = args.model or await get_model_info(base_url)
    if not model:
        print(f"\n{C.RED}❌ Servise bağlanılamadı: {base_url}{C.RESET}")
        sys.exit(1)
    print(f" {C.GREEN}✓{C.RESET}")

    print_header(base_url, model)

    # Parametreler
    concurrency_levels = args.concurrency or ([1, 2, 4] if args.quick else [1, 2, 4, 8, 12])
    concurrency_levels = sorted(set(concurrency_levels))
    if any(c < 1 for c in concurrency_levels):
        print(f"{C.RED}❌ Hatalı concurrency değeri: tüm değerler 1 veya büyük olmalı.{C.RESET}")
        sys.exit(1)
    if any(c > MAX_CONCURRENCY for c in concurrency_levels):
        print(
            f"{C.RED}❌ Hatalı concurrency değeri: en yüksek değer {MAX_CONCURRENCY} olabilir.{C.RESET}"
        )
        sys.exit(1)
    prompt_keys = args.prompts or (["short", "medium"] if args.quick else list(PROMPTS.keys()))
    num_requests_map = {
        1: 3 if args.quick else 5,
        2: 4 if args.quick else 8,
        4: 4 if args.quick else 8,
        8: 4 if args.quick else 8,
        12: 4 if args.quick else 12,
    }

    all_results: List[BenchmarkResult] = []

    # ── Bölüm 1: Tek istek (baseline) ─────────────────────────────────────────
    print_section("TEK İSTEK (Baseline)")
    max_tps_single = 1.0
    single_results = []

    for pk in prompt_keys:
        print(f"  {C.GRAY}  → {PROMPTS[pk]['label']} test ediliyor...{C.RESET}", end="\r")
        r = await run_benchmark(base_url, model, pk, 1, num_requests_map[1])
        single_results.append(r)
        all_results.append(r)
        if r.throughput_tok_s > max_tps_single:
            max_tps_single = r.throughput_tok_s

    for r in single_results:
        print_result_row(r, max_tps_single)

    # ── Bölüm 2: Concurrent ───────────────────────────────────────────────────
    if len(concurrency_levels) > 1 or (len(concurrency_levels) == 1 and concurrency_levels[0] > 1):
        conc_levels = [c for c in concurrency_levels if c > 1]
        for pk in prompt_keys:
            print_section(f"CONCURRENT — {PROMPTS[pk]['label']}")
            conc_results = []
            max_tps_conc = 1.0

            for c in conc_levels:
                num_req = num_requests_map.get(c, c * 2)
                print(f"  {C.GRAY}  → c={c}, {num_req} istek gönderiliyor...{C.RESET}", end="\r")
                r = await run_benchmark(base_url, model, pk, c, num_req)
                conc_results.append(r)
                all_results.append(r)
                if r.throughput_tok_s > max_tps_conc:
                    max_tps_conc = r.throughput_tok_s

            for r in conc_results:
                print_result_row(r, max_tps_conc)

    # ── Özet ──────────────────────────────────────────────────────────────────
    print_summary_table(all_results)

    report_path = args.json or default_report_filename()
    report_dir = os.path.dirname(report_path)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)
    save_json(
        all_results,
        report_path,
        base_url=base_url,
        model=model,
        prompt_keys=prompt_keys,
        concurrency_levels=concurrency_levels,
        quick_mode=args.quick,
    )


if __name__ == "__main__":
    asyncio.run(main())
