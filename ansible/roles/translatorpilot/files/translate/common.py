import json
import logging
from typing import List, Dict, Any

from contracts import Segment
from cache import CacheManager

logger = logging.getLogger("translate")


def strip_markdown_fences(text: str) -> str:
    """去除大语言模型输出文本中可能存在的 Markdown 代码块包裹符 (如 ```json ... ```)。"""
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text


def build_system_prompt(config: dict, num_items: int) -> tuple[str, str]:
    """生成系统提示词，强制组合翻译风格指南及必须遵守的 JSON 格式和条目数量约束。"""
    system_instruction = config["system_prompt"]
    style_guide = config["style_guide"]

    system_instruction += "\n\n" + style_guide
    base_system_instruction = system_instruction

    system_instruction += '\nOutput JSON format: {"translations": [{"id": "...", "translated_text": "..."}]}'
    system_instruction += (
        f"\nCRITICAL: You are given {num_items} segments. "
        f"Your JSON array MUST contain exactly {num_items} items. DO NOT skip any IDs."
    )
    system_instruction += (
        "\nCRITICAL: Output raw UTF-8 Chinese characters. DO NOT use \\uXXXX unicode escaping."
    )

    return base_system_instruction, system_instruction


def build_user_prompt(config: dict, items_to_translate: List[Dict[str, str]]) -> str:
    """将待翻译的数据条目编码成 JSON 字符串，作为用户提示词发送给大模型。"""
    user_instruction = config["user_prompt"]
    return f"{user_instruction}\n{json.dumps(items_to_translate, indent=2)}"


def check_cache(cache: CacheManager, cache_key: str, enable_cache: bool) -> bool:
    """检查当前批次翻译数据是否存在有效的本地缓存。"""
    return enable_cache and cache.exists(cache_key, ".json")


def load_from_cache(cache: CacheManager, cache_key: str) -> List[Dict[str, str]]:
    """从磁盘缓存加载 JSON 翻译结果。"""
    return cache.load_json(cache_key)


def save_to_cache(
    cache: CacheManager,
    cache_key: str,
    translations: List[Dict[str, str]],
    enable_cache: bool,
) -> None:
    """将成功的翻译结果落盘保存到本地 JSON 缓存。"""
    if enable_cache:
        cache.save_json(cache_key, translations)


def map_translations_to_segments(
    segments: List[Segment],
    translations: List[Dict[str, str]],
) -> List[Segment]:
    """遍历并将大模型返回的翻译结果根据段落 ID 正确地反向映射到原始的段落列表中。"""
    translation_map = {item["id"]: item["translated_text"] for item in translations}

    for seg in segments:
        if seg.segment_id not in translation_map:
            logger.error(f"[Translate] Missing translation for segment {seg.segment_id}")
            raise RuntimeError("Fatal pipeline error")
        seg.target_text = translation_map[seg.segment_id]

    return segments
