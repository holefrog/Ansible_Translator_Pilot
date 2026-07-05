"""
benchmark_translate.py
======================
针对 translate role 中所有翻译提供商/模型的性能与结果基准测试。
支持多轮运行，每轮之间等待指定秒数（默认 30s），用于触发并观察 429 限速行为。

测试文本（英→中）：
  "In modern software engineering, the transition from monolithic architectures
   to microservices has fundamentally reshaped how applications are developed,
   deployed, and scaled. While microservices offer unprecedented flexibility and
   fault isolation, they also introduce significant complexity in network
   communication and data consistency. Engineering teams must carefully weigh
   these trade-offs, often adopting container orchestration platforms to manage
   the intricate web of interdependent services effectively."

使用方式（在 translator-pilot 的 venv 中运行）：
  cd /home/david/translator-pilot

  # 单轮（默认）
  .venv/bin/python /home/david/Coding/Ansible_Translator_Pilot/tests/benchmark_translate.py

  # 多轮，间隔 30 秒
  .venv/bin/python /home/david/Coding/Ansible_Translator_Pilot/tests/benchmark_translate.py --runs 5 --interval 30

结果输出到终端，并保存为 JSON 到 benchmark_translate_results.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field

# ──────────────────────────────────────────────────────────────────────────────
# 确保 translator-pilot 运行目录在 sys.path 中
# ──────────────────────────────────────────────────────────────────────────────
RUNTIME_DIR = "/home/david/translator-pilot"
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

# ──────────────────────────────────────────────────────────────────────────────
# 加载 settings.toml
# ──────────────────────────────────────────────────────────────────────────────
try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

SETTINGS_PATH = os.path.join(RUNTIME_DIR, "settings.toml")
with open(SETTINGS_PATH, "rb") as _f:
    _settings = tomllib.load(_f)

# ──────────────────────────────────────────────────────────────────────────────
# 基准测试配置
# ──────────────────────────────────────────────────────────────────────────────
BENCHMARK_TEXT = (
    "In modern software engineering, the transition from monolithic architectures "
    "to microservices has fundamentally reshaped how applications are developed, "
    "deployed, and scaled. While microservices offer unprecedented flexibility and "
    "fault isolation, they also introduce significant complexity in network "
    "communication and data consistency. Engineering teams must carefully weigh "
    "these trade-offs, often adopting container orchestration platforms to manage "
    "the intricate web of interdependent services effectively."
)

# (provider_key, display_name, model_override_or_None)
PROVIDERS_TO_TEST = [
    ("groq_llm",   "Groq LLM",   None),
    ("nvidia_llm", "NVIDIA LLM", None),
    ("gemini",     "Gemini",     None),
    ("openai",     "OpenAI",     None),
    ("mistral",    "Mistral",    None),
]

# 不重试，真实计时
NO_RETRY_CONFIG = {
    "max_retries": 0,
    "base_delay": 0.0,
    "backoff_factor": 1.0,
    "max_delay": 0.0,
}

# ──────────────────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class BenchmarkResult:
    run:         int
    provider:    str
    model:       str
    elapsed_sec: float = 0.0
    translated:  str   = ""
    success:     bool  = False
    error:       str   = ""


# ──────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────────────────────
def _build_provider_config(provider_key: str, model_override: str | None) -> dict:
    common   = dict(_settings.get("translate", {}).get("common", {}))
    specific = dict(_settings.get("translate", {}).get(provider_key, {}))
    cfg = {**common, **specific}
    cfg["enable_cache"] = False
    if model_override:
        cfg["model"] = model_override
    return cfg


def _instantiate_provider(provider_key: str, config: dict):
    from translate.translate_groq_llm   import GroqTranslate
    from translate.translate_nvidia_llm import NvidiaTranslate
    from translate.translate_gemini     import GeminiTranslate
    from translate.translate_openai     import OpenAITranslate
    from translate.translate_mistral    import MistralTranslate

    cls_map = {
        "groq_llm":   GroqTranslate,
        "nvidia_llm": NvidiaTranslate,
        "gemini":     GeminiTranslate,
        "openai":     OpenAITranslate,
        "mistral":    MistralTranslate,
    }
    return cls_map[provider_key](config=config, retry_config=NO_RETRY_CONFIG)


def _run_single(run_no: int, provider_key: str, display_name: str,
                model_override: str | None) -> BenchmarkResult:
    from contracts import Segment

    config = _build_provider_config(provider_key, model_override)
    model  = config.get("model", "unknown")
    seg    = Segment(segment_id="seg-001", source_text=BENCHMARK_TEXT)
    result = BenchmarkResult(run=run_no, provider=display_name, model=model)

    t0 = time.perf_counter()
    try:
        provider = _instantiate_provider(provider_key, config)
        segments = provider.translate([seg])
        result.elapsed_sec = round(time.perf_counter() - t0, 3)
        result.translated  = segments[0].target_text or ""
        result.success     = True
    except Exception as exc:
        result.elapsed_sec = round(time.perf_counter() - t0, 3)
        result.error       = str(exc)
        result.success     = False

    return result


# ──────────────────────────────────────────────────────────────────────────────
# 输出格式化
# ──────────────────────────────────────────────────────────────────────────────
W = 82  # banner width

def _banner(text: str) -> None:
    print("\n" + "═" * W)
    print(f"  {text}")
    print("═" * W)


def _print_run_results(run_no: int, results: list[BenchmarkResult]) -> None:
    _banner(f"第 {run_no} 轮  —  逐条详细结果")
    for i, r in enumerate(results, start=1):
        icon = "✅" if r.success else "❌"
        print(f"\n  [{i}] {icon} {r.provider}  |  {r.model}")
        print(f"      耗时: {r.elapsed_sec:.3f}s")
        if r.success:
            # wrap at 64 chars
            lines = [r.translated[j:j+64] for j in range(0, len(r.translated), 64)]
            print(f"      译文: {lines[0]}")
            for ln in lines[1:]:
                print(f"            {ln}")
        else:
            print(f"      错误: {r.error[:260]}")


def _print_multi_run_summary(all_results: list[BenchmarkResult]) -> None:
    """跨轮次汇总：每个提供商的 min/avg/max 耗时及成功率。"""
    _banner("多轮汇总 — 各提供商统计（耗时 单位:秒）")

    providers = [p[1] for p in PROVIDERS_TO_TEST]  # display names in order

    COL = [18, 32, 8, 8, 8, 8, 10]
    header = (
        f"{'提供商':<{COL[0]}}"
        f"{'模型':<{COL[1]}}"
        f"{'最快':>{COL[2]}}"
        f"{'最慢':>{COL[3]}}"
        f"{'平均':>{COL[4]}}"
        f"{'中位':>{COL[5]}}"
        f"{'成功率':>{COL[6]}}"
    )
    sep = "─" * sum(COL)
    print(header)
    print(sep)

    for display in providers:
        rows = [r for r in all_results if r.provider == display]
        model = rows[0].model if rows else "?"
        model_short = model if len(model) <= COL[1] - 1 else model[:COL[1]-4] + "..."

        ok   = [r for r in rows if r.success]
        fail = len(rows) - len(ok)

        if ok:
            times  = sorted(r.elapsed_sec for r in ok)
            mn     = times[0]
            mx     = times[-1]
            avg    = sum(times) / len(times)
            mid_i  = len(times) // 2
            median = times[mid_i] if len(times) % 2 else (times[mid_i-1]+times[mid_i])/2
            rate   = f"{len(ok)}/{len(rows)}"
        else:
            mn = mx = avg = median = 0.0
            rate = f"0/{len(rows)}"

        print(
            f"{display:<{COL[0]}}"
            f"{model_short:<{COL[1]}}"
            f"{mn:>{COL[2]}.3f}"
            f"{mx:>{COL[3]}.3f}"
            f"{avg:>{COL[4]}.3f}"
            f"{median:>{COL[5]}.3f}"
            f"{rate:>{COL[6]}}"
        )
    print(sep)

    # 跨所有轮次找出 429 / rate-limit 错误
    rate_limited = [r for r in all_results if not r.success and "429" in r.error]
    if rate_limited:
        print(f"\n  ⚠️  共检测到 {len(rate_limited)} 次 429 限速：")
        for r in rate_limited:
            print(f"     轮次 {r.run}  {r.provider}  ({r.model})  — {r.error[:120]}")
    else:
        print("\n  ℹ️  本次测试未触发 429 限速。")


def _print_per_round_table(all_results: list[BenchmarkResult], num_runs: int) -> None:
    """按轮次展示每个提供商的耗时热力图式表格。"""
    _banner("各轮次耗时明细（✅成功 / ❌失败）")

    providers = [p[1] for p in PROVIDERS_TO_TEST]
    col_p = 18
    col_r = 12

    # header
    header = f"{'提供商':<{col_p}}" + "".join(f"{'第'+str(i)+'轮':>{col_r}}" for i in range(1, num_runs+1))
    print(header)
    print("─" * (col_p + col_r * num_runs))

    for display in providers:
        row_str = f"{display:<{col_p}}"
        for rn in range(1, num_runs + 1):
            hit = [r for r in all_results if r.provider == display and r.run == rn]
            if hit:
                r = hit[0]
                cell = f"✅{r.elapsed_sec:.2f}s" if r.success else "❌429" if "429" in r.error else "❌ERR"
            else:
                cell = "—"
            row_str += f"{cell:>{col_r}}"
        print(row_str)


# ──────────────────────────────────────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Translate Role 多轮基准测试")
    parser.add_argument("--runs",     type=int, default=1,  help="总运行轮次（默认 1）")
    parser.add_argument("--interval", type=int, default=30, help="轮次间隔秒数（默认 30）")
    args = parser.parse_args()

    num_runs = args.runs
    interval = args.interval

    _banner(
        f"Translate Role 基准测试  —  {num_runs} 轮 × {len(PROVIDERS_TO_TEST)} 个提供商"
        f"  |  间隔 {interval}s"
    )
    print(f"\n📝 源文本（{len(BENCHMARK_TEXT)} 字符）：")
    print(f"  {BENCHMARK_TEXT[:80]}...\n")

    all_results: list[BenchmarkResult] = []
    start_wall = time.time()

    for run_no in range(1, num_runs + 1):
        _banner(f"▶ 第 {run_no}/{num_runs} 轮  开始")

        run_results: list[BenchmarkResult] = []
        for idx, (key, display, override) in enumerate(PROVIDERS_TO_TEST, start=1):
            print(f"  [{idx}/{len(PROVIDERS_TO_TEST)}] {display} ... ", end="", flush=True)
            r = _run_single(run_no, key, display, override)
            run_results.append(r)
            all_results.append(r)
            tag = f"✅ {r.elapsed_sec:.3f}s" if r.success else f"❌ {r.error[:60]}"
            print(tag)

        # 本轮详细
        _print_run_results(run_no, run_results)

        # 轮间等待
        if run_no < num_runs:
            print(f"\n  ⏳ 等待 {interval} 秒后开始第 {run_no+1} 轮...", end="", flush=True)
            for remaining in range(interval, 0, -5):
                time.sleep(min(5, remaining))
                print(f" {remaining-min(5,remaining)}s", end="", flush=True)
            print(" → 开始！")

    # ── 多轮汇总
    _print_per_round_table(all_results, num_runs)
    _print_multi_run_summary(all_results)

    total_wall = time.time() - start_wall
    print(f"\n  ⏱  总计耗时: {total_wall:.1f}s  ({num_runs} 轮)")

    # ── 保存 JSON
    output_path = os.path.join(RUNTIME_DIR, "benchmark_translate_results.json")
    payload = {
        "config": {
            "num_runs": num_runs,
            "interval_sec": interval,
            "benchmark_text": BENCHMARK_TEXT,
            "providers": [{"key": k, "display": d, "model_override": o}
                          for k, d, o in PROVIDERS_TO_TEST],
        },
        "results": [
            {
                "run":         r.run,
                "provider":    r.provider,
                "model":       r.model,
                "elapsed_sec": r.elapsed_sec,
                "success":     r.success,
                "translated":  r.translated,
                "error":       r.error,
            }
            for r in all_results
        ],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"💾 结果已保存到: {output_path}\n")


if __name__ == "__main__":
    os.chdir(RUNTIME_DIR)
    main()
