"""
benchmark_translate.py
======================
针对 translate role 中所有翻译提供商/模型的性能与结果基准测试。
支持多轮运行，每轮之间等待指定秒数（默认 2s），用于触发并观察 429 限速行为。

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

  # 多轮，间隔 2 秒（触发限速）
  .venv/bin/python /home/david/Coding/Ansible_Translator_Pilot/tests/benchmark_translate.py --runs 5 --interval 2

结果（JSON + Markdown 报告）保存到脚本所在目录：
  /home/david/Coding/Ansible_Translator_Pilot/tests/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

# ──────────────────────────────────────────────────────────────────────────────
# 目录常量
# ──────────────────────────────────────────────────────────────────────────────
RUNTIME_DIR = "/home/david/translator-pilot"          # 运行时依赖（modules）
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))  # 脚本 & 结果所在目录

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

# 使用 retry.py 的真实重试配置：最多 5 次，基础间隔 2s，指数退避，上限 60s
BENCHMARK_RETRY_CONFIG = {
    "max_retries":    5,
    "base_delay":     2.0,
    "backoff_factor": 2.0,
    "max_delay":      60.0,
}

# ──────────────────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class BenchmarkResult:
    run:              int
    provider:         str
    model:            str
    elapsed_sec:      float = 0.0   # 含重试等待的总耗时
    translated:       str   = ""
    success:          bool  = False
    error:            str   = ""
    retry_attempts:   int   = 0     # 实际触发的重试次数
    retry_delay_sec:  float = 0.0   # 重试等待总秒数（估算）


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
    # 传入真实 retry config；with_retry 会在外层再包一层，这里的 config 内的重试由
    # BatchedTranslateProvider.translate() 自身使用（http_utils.run_with_http_retry）。
    # 为避免双重重试，传给 provider 的 retry_config 保持 0 次，由外层 with_retry 控制。
    return cls_map[provider_key](config=config, retry_config={"max_retries": 0, "base_delay": 0.0, "backoff_factor": 1.0, "max_delay": 0.0})


def _run_single(run_no: int, provider_key: str, display_name: str,
                model_override: str | None) -> BenchmarkResult:
    """
    调用翻译提供商，使用 retry.py 的 with_retry() 包裹，
    实现最多 5 次重试、基础 2s 指数退避，并记录重试次数与总耗时。
    """
    from contracts import Segment
    from retry import with_retry, is_rate_limited, parse_rate_limit_delay

    config = _build_provider_config(provider_key, model_override)
    model  = config.get("model", "unknown")
    seg    = Segment(segment_id="seg-001", source_text=BENCHMARK_TEXT)
    result = BenchmarkResult(run=run_no, provider=display_name, model=model)

    # 用于在闭包中追踪重试次数
    attempt_counter = {"count": 0, "delay_total": 0.0}

    # monkey-patch time.sleep 以统计重试等待时间
    _orig_sleep = time.sleep
    def _tracking_sleep(secs: float) -> None:
        attempt_counter["count"] += 1
        attempt_counter["delay_total"] += secs
        print(f"  ↻ 重试等待 {secs:.1f}s ...", end="", flush=True)
        _orig_sleep(secs)
        print(" 重试中")

    t0 = time.perf_counter()
    try:
        time.sleep = _tracking_sleep  # type: ignore[assignment]
        provider   = _instantiate_provider(provider_key, config)

        def _do_translate():
            # 每次重试需要一个新 Segment（target_text 可能被部分修改）
            fresh_seg = Segment(segment_id="seg-001", source_text=BENCHMARK_TEXT)
            return provider.translate([fresh_seg])

        segments = with_retry(
            _do_translate,
            BENCHMARK_RETRY_CONFIG,
            label=f"{display_name} benchmark",
        )
        result.elapsed_sec     = round(time.perf_counter() - t0, 3)
        result.translated      = segments[0].target_text or ""
        result.success         = True
        result.retry_attempts  = attempt_counter["count"]
        result.retry_delay_sec = round(attempt_counter["delay_total"], 1)
    except Exception as exc:
        result.elapsed_sec     = round(time.perf_counter() - t0, 3)
        result.error           = str(exc)
        result.success         = False
        result.retry_attempts  = attempt_counter["count"]
        result.retry_delay_sec = round(attempt_counter["delay_total"], 1)
    finally:
        time.sleep = _orig_sleep  # 恢复原始 sleep

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
        retry_info = f"  [重试 {r.retry_attempts} 次 / 等待 {r.retry_delay_sec:.1f}s]" if r.retry_attempts else ""
        print(f"\n  [{i}] {icon} {r.provider}  |  {r.model}{retry_info}")
        print(f"      总耗时: {r.elapsed_sec:.3f}s")
        if r.success:
            # wrap at 64 chars
            lines = [r.translated[j:j+64] for j in range(0, len(r.translated), 64)]
            print(f"      译文: {lines[0]}")
            for ln in lines[1:]:
                print(f"            {ln}")
        else:
            print(f"      错误: {r.error[:260]}")


def _print_multi_run_summary(all_results: list[BenchmarkResult]) -> None:
    """跨轮次汇总：每个提供商的 min/avg/max/total 耗时及成功率。"""
    _banner("多轮汇总 — 各提供商统计（耗时 单位:秒）")

    providers = [p[1] for p in PROVIDERS_TO_TEST]

    COL = [18, 30, 8, 8, 8, 8, 9, 9]
    header = (
        f"{'提供商':<{COL[0]}}"
        f"{'模型':<{COL[1]}}"
        f"{'最快':>{COL[2]}}"
        f"{'最慢':>{COL[3]}}"
        f"{'平均':>{COL[4]}}"
        f"{'中位':>{COL[5]}}"
        f"{'总耗时':>{COL[6]}}"
        f"{'成功率':>{COL[7]}}"
    )
    sep = "─" * sum(COL)
    print(header)
    print(sep)

    for display in providers:
        rows = [r for r in all_results if r.provider == display]
        model = rows[0].model if rows else "?"
        model_short = model if len(model) <= COL[1] - 1 else model[:COL[1]-4] + "..."

        ok = [r for r in rows if r.success]

        if ok:
            times  = sorted(r.elapsed_sec for r in ok)
            mn     = times[0]
            mx     = times[-1]
            avg    = sum(times) / len(times)
            mid_i  = len(times) // 2
            median = times[mid_i] if len(times) % 2 else (times[mid_i-1]+times[mid_i])/2
            total  = sum(times)
            rate   = f"{len(ok)}/{len(rows)}"
        else:
            mn = mx = avg = median = total = 0.0
            rate = f"0/{len(rows)}"

        print(
            f"{display:<{COL[0]}}"
            f"{model_short:<{COL[1]}}"
            f"{mn:>{COL[2]}.3f}"
            f"{mx:>{COL[3]}.3f}"
            f"{avg:>{COL[4]}.3f}"
            f"{median:>{COL[5]}.3f}"
            f"{total:>{COL[6]}.2f}"
            f"{rate:>{COL[7]}}"
        )
    print(sep)

    # 跨所有轮次找出 429 / rate-limit 错误
    # 注意：retry.py 消化掉的 429 不会出现在 success=False 里，
    # 但会导致 elapsed_sec 异常偏大，以及 retry_attempts > 0。
    rate_limited = [r for r in all_results if not r.success and "429" in r.error]
    retried      = [r for r in all_results if r.retry_attempts > 0]
    if rate_limited:
        print(f"\n  ⚠️  共检测到 {len(rate_limited)} 次未恢复的 429 限速：")
        for r in rate_limited:
            print(f"     轮次 {r.run}  {r.provider}  ({r.model})  — {r.error[:120]}")
    else:
        print("\n  ℹ️  无未恢复的 429 限速（成功结果中可能含重试）。")
    if retried:
        print(f"\n  🔁  以下请求触发了重试（retry.py 已恢复）：")
        for r in retried:
            print(f"     轮次 {r.run}  {r.provider}  重试 {r.retry_attempts} 次 / 等待 {r.retry_delay_sec:.1f}s")


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
    parser.add_argument("--runs",     type=int, default=1, help="总运行轮次（默认 1）")
    parser.add_argument("--interval", type=int, default=2, help="轮次间隔秒数（默认 2）")
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

    # ── 保存 JSON（保存到脚本目录）
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_filename = f"benchmark_results_{ts}.json"
    json_path = os.path.join(SCRIPT_DIR, json_filename)

    payload = {
        "config": {
            "timestamp": ts,
            "num_runs": num_runs,
            "interval_sec": interval,
            "benchmark_text": BENCHMARK_TEXT,
            "providers": [{"key": k, "display": d, "model_override": o}
                          for k, d, o in PROVIDERS_TO_TEST],
        },
        "results": [
            {
                "run":              r.run,
                "provider":         r.provider,
                "model":            r.model,
                "elapsed_sec":      r.elapsed_sec,
                "success":          r.success,
                "retry_attempts":   r.retry_attempts,
                "retry_delay_sec":  r.retry_delay_sec,
                "translated":       r.translated,
                "error":            r.error,
            }
            for r in all_results
        ],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"💾 JSON 已保存到  : {json_path}")

    # ── 保存 Markdown 分析报告（保存到脚本目录）
    md_filename = f"benchmark_report_{ts}.md"
    md_path = os.path.join(SCRIPT_DIR, md_filename)
    _save_markdown_report(md_path, all_results, num_runs, interval, ts, total_wall)
    print(f"📄 报告已保存到  : {md_path}\n")


# ──────────────────────────────────────────────────────────────────────────────
# Markdown 报告生成
# ──────────────────────────────────────────────────────────────────────────────
def _save_markdown_report(
    path: str,
    all_results: list[BenchmarkResult],
    num_runs: int,
    interval: int,
    ts: str,
    total_wall: float,
) -> None:
    providers = [p[1] for p in PROVIDERS_TO_TEST]
    lines: list[str] = []

    lines.append(f"# Translate Role 基准测试报告")
    lines.append(f"")
    lines.append(f"- **时间戳**: `{ts}`")
    lines.append(f"- **轮次**: {num_runs}  |  **间隔**: {interval}s  |  **总耗时**: {total_wall:.1f}s")
    lines.append(f"- **提供商数**: {len(PROVIDERS_TO_TEST)}")
    lines.append(f"- **重试配置**: 最多 {BENCHMARK_RETRY_CONFIG['max_retries']} 次 / 基础间隔 {BENCHMARK_RETRY_CONFIG['base_delay']}s / 指数退避 {BENCHMARK_RETRY_CONFIG['backoff_factor']}x / 上限 {BENCHMARK_RETRY_CONFIG['max_delay']}s")
    lines.append(f"")
    lines.append(f"## 源文本")
    lines.append(f"")
    lines.append(f"> {BENCHMARK_TEXT}")
    lines.append(f"")

    # 各轮次耗时表
    lines.append(f"## 各轮次耗时明细")
    lines.append(f"")
    header_cols = ["提供商"] + [f"第{i}轮" for i in range(1, num_runs + 1)]
    lines.append("| " + " | ".join(header_cols) + " |")
    lines.append("|" + "---|" * len(header_cols))
    for display in providers:
        row = [display]
        for rn in range(1, num_runs + 1):
            hit = [r for r in all_results if r.provider == display and r.run == rn]
            if hit:
                r = hit[0]
                if r.success:
                    cell = f"✅ {r.elapsed_sec:.2f}s"
                elif "429" in r.error:
                    cell = "❌ 429"
                else:
                    cell = "❌ ERR"
            else:
                cell = "—"
            row.append(cell)
        lines.append("| " + " | ".join(row) + " |")
    lines.append(f"")

    # 统计汇总表（含重试列 + 总耗时 + 轮均）
    lines.append(f"## 多轮统计汇总")
    lines.append(f"")
    lines.append("| 提供商 | 模型 | 最快(s) | 最慢(s) | 平均(s) | 中位(s) | 总耗时(s) | 轮均(s) | 成功率 | 重试总次 | 重试等待(s) |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|:---:|---:|---:|")
    for display in providers:
        rows = [r for r in all_results if r.provider == display]
        model = rows[0].model if rows else "?"
        ok = [r for r in rows if r.success]
        total_retries    = sum(r.retry_attempts  for r in rows)
        total_retry_wait = sum(r.retry_delay_sec for r in rows)
        if ok:
            times  = sorted(r.elapsed_sec for r in ok)
            mn     = times[0]
            mx     = times[-1]
            avg    = sum(times) / len(times)
            mid_i  = len(times) // 2
            median = times[mid_i] if len(times) % 2 else (times[mid_i-1] + times[mid_i]) / 2
            total  = sum(times)
            per_rn = total / len(rows)   # 含失败轮次的真实轮均
            rate   = f"{len(ok)}/{len(rows)}"
        else:
            mn = mx = avg = median = total = per_rn = 0.0
            rate = f"0/{len(rows)}"
        lines.append(
            f"| {display} | `{model}` | {mn:.3f} | {mx:.3f} | {avg:.3f} | {median:.3f}"
            f" | {total:.2f} | {per_rn:.2f} | {rate} | {total_retries} | {total_retry_wait:.1f} |"
        )
    lines.append(f"")

    # 429 / 错误汇总
    rate_limited = [r for r in all_results if not r.success and "429" in r.error]
    other_errors = [r for r in all_results if not r.success and "429" not in r.error]
    lines.append(f"## 错误汇总")
    lines.append(f"")
    if rate_limited:
        lines.append(f"### ⚠️ 429 限速事件 ({len(rate_limited)} 次)")
        lines.append(f"")
        for r in rate_limited:
            lines.append(f"- 轮次 {r.run} · **{r.provider}** (`{r.model}`): `{r.error[:150]}`")
        lines.append(f"")
    else:
        lines.append(f"> ℹ️ 本次测试未触发任何 429 限速。")
        lines.append(f"")
    if other_errors:
        lines.append(f"### ❌ 其他错误 ({len(other_errors)} 次)")
        lines.append(f"")
        for r in other_errors:
            lines.append(f"- 轮次 {r.run} · **{r.provider}** (`{r.model}`): `{r.error[:150]}`")
        lines.append(f"")

    # 完整译文（仅成功的）
    lines.append(f"## 完整译文对比（第1轮）")
    lines.append(f"")
    for display in providers:
        hit = [r for r in all_results if r.provider == display and r.run == 1 and r.success]
        if hit:
            r = hit[0]
            lines.append(f"### {display} · `{r.model}`")
            lines.append(f"")
            lines.append(f"> {r.translated}")
            lines.append(f"")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    # 切换到运行目录，使相对路径导入（prompts/、cache/ 等）正常工作
    os.chdir(RUNTIME_DIR)
    main()
