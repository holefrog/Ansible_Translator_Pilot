import json
import logging
from typing import List, Dict, Any

from contracts import Segment
from cache import CacheManager

logger = logging.getLogger("translate")


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code block fences (```json or ```) from model output."""
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text


def build_system_prompt(config: dict, num_items: int) -> tuple[str, str]:
    """Build system prompt with style guide and translation constraints."""
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
    """Build user prompt with JSON array of items to translate."""
    user_instruction = config["user_prompt"]
    return f"{user_instruction}\n{json.dumps(items_to_translate, indent=2)}"


def check_cache(cache: CacheManager, cache_key: str, enable_cache: bool) -> bool:
    """Check if cached translation exists."""
    return enable_cache and cache.exists(cache_key, ".json")


def load_from_cache(cache: CacheManager, cache_key: str) -> List[Dict[str, str]]:
    """Load translations from cache."""
    return cache.load_json(cache_key)


def save_to_cache(
    cache: CacheManager,
    cache_key: str,
    translations: List[Dict[str, str]],
    enable_cache: bool,
) -> None:
    """Save translations to cache."""
    if enable_cache:
        cache.save_json(cache_key, translations)


def map_translations_to_segments(
    segments: List[Segment],
    translations: List[Dict[str, str]],
) -> List[Segment]:
    """Map parsed translations back to segments and check for missing IDs."""
    translation_map = {item["id"]: item["translated_text"] for item in translations}

    for seg in segments:
        if seg.segment_id not in translation_map:
            logger.error(f"[Translate] Missing translation for segment {seg.segment_id}")
            raise RuntimeError("Fatal pipeline error")
        seg.target_text = translation_map[seg.segment_id]

    return segments
