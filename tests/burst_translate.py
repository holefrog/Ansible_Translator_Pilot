"""
burst_translate.py
==================
对所有翻译提供商进行零间隔压力测试，找出各家免费层的实际限速门槛。

策略：
  - 每个提供商独立测试，连发 N 次（默认 20），请求之间零等待
  - 不使用 retry.py —— 我们要看原始 429 出现在第几次
  - 连续 5 次 429 后提前终止该提供商的测试
  - 记录每次请求结果并生成报告

使用方式（在 translator-pilot venv 中运行）：
  cd /home/david/translator-pilot
  .venv/bin/python /home/david/Coding/Ansible_Translator_Pilot/tests/burst_translate.py

  # 自定义请求次数
  .venv/bin/python /home/david/Coding/Ansible_Translator_Pilot/tests/burst_translate.py --count 30

结果保存在脚本所在目录：
  burst_results_<timestamp>.json
  burst_report_<timestamp>.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ──────────────────────────────────────────────────────────────────────────────
# 目录常量
# ──────────────────────────────────────────────────────────────────────────────
RUNTIME_DIR = "/home/david/translator-pilot"
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))

if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

# ──────────────────────────────────────────────────────────────────────────────
# 加载 settings.toml
# ──────────────────────────────────────────────────────────────────────────────
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

with open(os.path.join(RUNTIME_DIR, "settings.toml"), "rb") as _f:
    _settings = tomllib.load(_f)

# ──────────────────────────────────────────────────────────────────────────────
# 配置
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

PROVIDERS_TO_TEST = [
    ("groq_llm",   "Groq LLM",   None),
    ("nvidia_llm", "NVIDIA LLM", None),
    ("gemini",     "Gemini",     None),
    ("openai",     "OpenAI",     None),
    ("mistral",    "Mistral",    None),
]

# 零重试——看裸 429
NO_RETRY = {"max_retries": 0, "base_delay": 0.0, "backoff_factor": 1.0, "max_delay": 0.0}

# 连续 429 多少次后提前停止该提供商
CONSECUTIVE_429_ABORT = 5


# ──────────────────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class RequestResult:
    seq:         int           # 第几次请求（1-indexed）
    elapsed_sec: float = 0.0
    success:     bool  = False
    is_429:      bool  = False
    is_other_err: bool = False
    error:       str   = ""


@dataclass
class ProviderBurstResult:
    provider:          str
    model:             str
    requests:          list[RequestResult] = field(default_factory=list)
    first_429_at:      int   = 0    # 第几次出现第一个 429（0=未出现）
    total_success:     int   = 0
    total_429:         int   = 0
    total_other_err:   int   = 0
    aborted_early:     bool  = False
    abort_reason:      str   = ""


# ──────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────────────────────
def _build_config(provider_key: str) -> dict:
    common   = dict(_settings.get("translate", {}).get("common", {}))
    specific = dict(_settings.get("translate", {}).get(provider_key, {}))
    cfg = {**common, **specific}
    cfg["enable_cache"] = False
    return cfg


def _make_provider(provider_key: str, config: dict):
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
    return cls_map[provider_key](config=config, retry_config=NO_RETRY)


def _is_rate_limited(err: str) -> bool:
    lower = err.lower()
    return "429" in err or "rate_limit" in lower or "rate limit" in lower or "quota" in lower


def _run_burst(provider_key: str, display: str, count: int) -> ProviderBurstResult:
    from contracts import Segment

    config   = _build_config(provider_key)
    model    = config.get("model", "?")
    provider = _make_provider(provider_key, config)
    result   = ProviderBurstResult(provider=display, model=model)

    consecutive_429 = 0

    for seq in range(1, count + 1):
        seg = Segment(segment_id=f"burst-{seq:03d}", source_text=BENCHMARK_TEXT)
        rr  = RequestResult(seq=seq)
        t0  = time.perf_counter()
        try:
            segs = provider.translate([seg])
            rr.elapsed_sec = round(time.perf_counter() - t0, 3)
            rr.success     = True
            result.total_success += 1
            consecutive_429 = 0
            status_char = "✅"
        except Exception as exc:
            rr.elapsed_sec = round(time.perf_counter() - t0, 3)
            rr.error       = str(exc)
            if _is_rate_limited(rr.error):
                rr.is_429 = True
                result.total_429 += 1
                if result.first_429_at == 0:
                    result.first_429_at = seq
                consecutive_429 += 1
                status_char = "🚫"
            else:
                rr.is_other_err = True
                result.total_other_err += 1
                consecutive_429 = 0
                status_char = "❌"

        result.requests.append(rr)

        # 实时打印进度
        elapsed_str = f"{rr.elapsed_sec:.2f}s"
        print(f"    #{seq:02d} {status_char} {elapsed_str}", end="  ", flush=True)
        if seq % 5 == 0:
            print()  # 每5个换行

        # 连续 429 中止
        if consecutive_429 >= CONSECUTIVE_429_ABORT:
            result.aborted_early = True
            result.abort_reason  = (
                f"连续 {consecutive_429} 次 429，在第 {seq} 次后提前终止"
            )
            print(f"\n    ⛔ {result.abort_reason}")
            break

    if seq % 5 != 0:
        print()  # 补换行

    return result


# ──────────────────────────────────────────────────────────────────────────────
# 输出
# ──────────────────────────────────────────────────────────────────────────────
W = 82

def _banner(text: str) -> None:
    print("\n" + "═" * W)
    print(f"  {text}")
    print("═" * W)


def _print_provider_summary(r: ProviderBurstResult, count: int) -> None:
    done = len(r.requests)
    rate = r.total_success / done * 100 if done else 0
    print(f"\n  提供商 : {r.provider}  ({r.model})")
    print(f"  发送   : {done}/{count} 次请求")
    print(f"  ✅ 成功: {r.total_success}  🚫 429: {r.total_429}  ❌ 其他: {r.total_other_err}  ({rate:.0f}% 成功)")
    if r.first_429_at:
        print(f"  🚨 首次 429 出现在第 {r.first_429_at} 次请求")
    else:
        print(f"  🎉 全程未触发 429")
    if r.aborted_early:
        print(f"  ⛔ {r.abort_reason}")
    if r.total_success:
        ok_times = [req.elapsed_sec for req in r.requests if req.success]
        print(f"  ⏱  成功请求耗时: 最快 {min(ok_times):.2f}s / 平均 {sum(ok_times)/len(ok_times):.2f}s / 最慢 {max(ok_times):.2f}s")


def _print_final_summary(results: list[ProviderBurstResult], count: int) -> None:
    _banner("Burst 测试汇总 — 各提供商限速门槛")
    COL = [18, 32, 8, 8, 8, 10, 14]
    header = (
        f"{'提供商':<{COL[0]}}"
        f"{'模型':<{COL[1]}}"
        f"{'成功':>{COL[2]}}"
        f"{'429':>{COL[3]}}"
        f"{'其他错':>{COL[4]}}"
        f"{'首次429':>{COL[5]}}"
        f"{'结论':>{COL[6]}}"
    )
    sep = "─" * sum(COL)
    print(header)
    print(sep)
    for r in results:
        done = len(r.requests)
        if r.first_429_at:
            first = f"第 {r.first_429_at} 次"
        else:
            first = "未触发"
        if r.first_429_at == 0 and r.total_other_err == 0:
            verdict = "✅ 全过"
        elif r.first_429_at == 0:
            verdict = "⚠️ 非限速错"
        else:
            verdict = f"🚫 第{r.first_429_at}次限速"
        model_s = r.model if len(r.model) <= COL[1]-1 else r.model[:COL[1]-4]+"..."
        print(
            f"{r.provider:<{COL[0]}}"
            f"{model_s:<{COL[1]}}"
            f"{r.total_success:>{COL[2]}}"
            f"{r.total_429:>{COL[3]}}"
            f"{r.total_other_err:>{COL[4]}}"
            f"{first:>{COL[5]}}"
            f"{verdict:>{COL[6]}}"
        )
    print(sep)


# ──────────────────────────────────────────────────────────────────────────────
# Markdown 报告
# ──────────────────────────────────────────────────────────────────────────────
def _save_report(path: str, results: list[ProviderBurstResult],
                 count: int, ts: str, total_wall: float) -> None:
    lines: list[str] = []
    lines.append("# Translate Role Burst 压力测试报告")
    lines.append("")
    lines.append(f"- **时间戳**: `{ts}`")
    lines.append(f"- **每提供商最大请求数**: {count}  |  **请求间隔**: 0s (零等待)")
    lines.append(f"- **提前终止条件**: 连续 {CONSECUTIVE_429_ABORT} 次 429")
    lines.append(f"- **总耗时**: {total_wall:.1f}s")
    lines.append(f"- **重试策略**: 无（裸 429 直接记录）")
    lines.append("")
    lines.append("## 源文本")
    lines.append("")
    lines.append(f"> {BENCHMARK_TEXT}")
    lines.append("")

    # 汇总表
    lines.append("## 汇总：各提供商限速门槛")
    lines.append("")
    lines.append("| 提供商 | 模型 | 发送次数 | ✅ 成功 | 🚫 429 | ❌ 其他 | 首次429 | 结论 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---|")
    for r in results:
        done = len(r.requests)
        first = f"第 {r.first_429_at} 次" if r.first_429_at else "未触发"
        if r.first_429_at == 0 and r.total_other_err == 0:
            verdict = "✅ 全部通过"
        elif r.first_429_at == 0:
            verdict = "⚠️ 非限速错误"
        else:
            verdict = f"🚫 第 {r.first_429_at} 次起限速"
        lines.append(
            f"| {r.provider} | `{r.model}` | {done} | {r.total_success}"
            f" | {r.total_429} | {r.total_other_err} | {first} | {verdict} |"
        )
    lines.append("")

    # 各提供商逐次明细
    lines.append("## 各提供商逐次请求明细")
    lines.append("")
    for r in results:
        lines.append(f"### {r.provider}  (`{r.model}`)")
        lines.append("")
        if r.aborted_early:
            lines.append(f"> ⛔ **提前终止**: {r.abort_reason}")
            lines.append("")
        # 分组显示（每行10个）
        lines.append("```")
        row = []
        for req in r.requests:
            if req.success:
                cell = f"#{req.seq:02d}✅{req.elapsed_sec:.1f}s"
            elif req.is_429:
                cell = f"#{req.seq:02d}🚫429"
            else:
                cell = f"#{req.seq:02d}❌ERR"
            row.append(cell)
            if len(row) == 5:
                lines.append("  " + "  ".join(f"{c:<12}" for c in row))
                row = []
        if row:
            lines.append("  " + "  ".join(f"{c:<12}" for c in row))
        lines.append("```")
        lines.append("")
        if r.total_success:
            ok_times = [req.elapsed_sec for req in r.requests if req.success]
            lines.append(
                f"- 成功耗时：最快 {min(ok_times):.2f}s /"
                f" 平均 {sum(ok_times)/len(ok_times):.2f}s /"
                f" 最慢 {max(ok_times):.2f}s"
            )
        if r.first_429_at:
            lines.append(f"- **首次 429**: 第 {r.first_429_at} 次请求")
        lines.append("")

    # 分析结论
    lines.append("## 分析结论")
    lines.append("")
    no_limit = [r for r in results if not r.first_429_at and not r.total_other_err]
    has_limit = [r for r in results if r.first_429_at > 0]
    has_err   = [r for r in results if not r.first_429_at and r.total_other_err > 0]

    if no_limit:
        lines.append(f"### ✅ 零间隔 {count} 次全部通过（无限速）")
        lines.append("")
        for r in no_limit:
            lines.append(f"- **{r.provider}** (`{r.model}`)：{r.total_success}/{len(r.requests)} 成功")
        lines.append("")
    if has_limit:
        lines.append("### 🚫 触发限速")
        lines.append("")
        for r in has_limit:
            lines.append(
                f"- **{r.provider}**：第 {r.first_429_at} 次触发 429，"
                f"共 {r.total_429} 次限速 / {r.total_success} 次成功"
            )
        lines.append("")
    if has_err:
        lines.append("### ⚠️ 非限速错误")
        lines.append("")
        for r in has_err:
            lines.append(f"- **{r.provider}**：{r.total_other_err} 次非 429 错误")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ──────────────────────────────────────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Translate Role Burst 压力测试")
    parser.add_argument("--count", type=int, default=20, help="每提供商最大请求次数（默认 20）")
    args = parser.parse_args()
    count = args.count

    _banner(
        f"Burst 压力测试  —  {len(PROVIDERS_TO_TEST)} 个提供商 × {count} 次零间隔请求"
    )
    print(f"\n⚠️  此测试会故意触发限速，请求间无等待，目的是找各家免费层实际门槛。\n")
    print(f"📝 源文本: {BENCHMARK_TEXT[:70]}...\n")

    all_results: list[ProviderBurstResult] = []
    start_wall = time.time()

    for pidx, (key, display, _) in enumerate(PROVIDERS_TO_TEST, start=1):
        _banner(f"[{pidx}/{len(PROVIDERS_TO_TEST)}] {display}")
        r = _run_burst(key, display, count)
        all_results.append(r)
        _print_provider_summary(r, count)

    total_wall = time.time() - start_wall

    # 汇总
    _print_final_summary(all_results, count)
    print(f"\n  ⏱  总计耗时: {total_wall:.1f}s\n")

    # 保存
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = os.path.join(SCRIPT_DIR, f"burst_results_{ts}.json")
    md_path   = os.path.join(SCRIPT_DIR, f"burst_report_{ts}.md")

    payload = {
        "config": {
            "timestamp": ts, "count": count,
            "consecutive_429_abort": CONSECUTIVE_429_ABORT,
            "benchmark_text": BENCHMARK_TEXT,
        },
        "results": [
            {
                "provider":        r.provider,
                "model":           r.model,
                "first_429_at":    r.first_429_at,
                "total_success":   r.total_success,
                "total_429":       r.total_429,
                "total_other_err": r.total_other_err,
                "aborted_early":   r.aborted_early,
                "abort_reason":    r.abort_reason,
                "requests": [
                    {"seq": rq.seq, "elapsed_sec": rq.elapsed_sec,
                     "success": rq.success, "is_429": rq.is_429,
                     "is_other_err": rq.is_other_err, "error": rq.error[:200]}
                    for rq in r.requests
                ],
            }
            for r in all_results
        ],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    _save_report(md_path, all_results, count, ts, total_wall)

    print(f"💾 JSON : {json_path}")
    print(f"📄 报告 : {md_path}\n")


if __name__ == "__main__":
    os.chdir(RUNTIME_DIR)
    main()
