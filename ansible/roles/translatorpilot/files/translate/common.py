import os
import json
import logging
from typing import List, Dict, Any
from contracts import Segment
from cache import CacheManager

logger = logging.getLogger("translate")


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code block fences (```json or ```) from model output.
    
    Some models wrap JSON output in markdown code blocks. This function
    strips those fences to get the raw JSON content.
    
    Args:
        text: Raw model output that may contain markdown fences
        
    Returns:
        Text with markdown fences removed
    """
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text


def build_system_prompt(config: dict, num_items: int) -> tuple[str, str]:
    """Build system prompt with style guide and translation constraints.
    
    Args:
        config: Provider configuration dict
        num_items: Number of segments in current batch
        
    Returns:
        Tuple of (base_system_instruction, full_system_instruction)
        base_system_instruction is used for cache key generation
        full_system_instruction includes dynamic constraints
    """
    system_instruction = config["system_prompt"]
    if not system_instruction:
        logger.error("[Translate] System prompt is missing from config.")
        raise RuntimeError("Fatal pipeline error")
    
    style_guide_path = config.get("style_guide_path")
    if not style_guide_path:
        logger.error("[Translate] Style guide path is missing from config.")
        raise RuntimeError("Fatal pipeline error")
    
    if not os.path.exists(style_guide_path):
        logger.error(f"[Translate] Style guide file not found: {style_guide_path}")
        raise RuntimeError("Fatal pipeline error")
    
    with open(style_guide_path, "r", encoding="utf-8") as f:
        style_guide = f.read()
        system_instruction += "\n\n" + style_guide
    
    # Store base for cache key (before adding dynamic content)
    base_system_instruction = system_instruction
    
    # Add dynamic constraints
    system_instruction += "\nOutput JSON format: {\"translations\": [{\"id\": \"...\", \"translated_text\": \"...\"}]}"
    system_instruction += f"\nCRITICAL: You are given {num_items} segments. Your JSON array MUST contain exactly {num_items} items. DO NOT skip any IDs."
    system_instruction += "\nCRITICAL: Output raw UTF-8 Chinese characters. DO NOT use \\uXXXX unicode escaping."
    
    return base_system_instruction, system_instruction


def build_user_prompt(config: dict, items_to_translate: List[Dict[str, str]]) -> str:
    """Build user prompt with JSON array of items to translate.
    
    Args:
        config: Provider configuration dict
        items_to_translate: List of dicts with 'id' and 'text' keys
        
    Returns:
        Complete user prompt string
    """
    user_instruction = config["user_prompt"]
    if not user_instruction:
        logger.error("[Translate] User prompt is missing from config.")
        raise RuntimeError("Fatal pipeline error")
    
    return f"{user_instruction}\n{json.dumps(items_to_translate, indent=2)}"


def get_cache_key(cache: CacheManager, base_system_instruction: str, 
                  user_prompt: str, model: str) -> str:
    """Generate cache key from stable parameters.
    
    Args:
        cache: CacheManager instance
        base_system_instruction: System prompt without dynamic constraints
        user_prompt: User prompt with items to translate
        model: Model name
        
    Returns:
        Cache key string
    """
    return cache.get_cache_key(base_system_instruction, user_prompt, model)


def check_cache(cache: CacheManager, cache_key: str, enable_cache: bool) -> bool:
    """Check if cached translation exists.
    
    Args:
        cache: CacheManager instance
        cache_key: Cache key to check
        enable_cache: Whether caching is enabled
        
    Returns:
        True if cache hit, False otherwise
    """
    return enable_cache and cache.exists(cache_key, ".json")


def load_from_cache(cache: CacheManager, cache_key: str) -> List[Dict[str, str]]:
    """Load translations from cache.
    
    Args:
        cache: CacheManager instance
        cache_key: Cache key to load
        
    Returns:
        List of translation dicts
    """
    return cache.load_json(cache_key)


def save_to_cache(cache: CacheManager, cache_key: str, 
                  translations: List[Dict[str, str]], enable_cache: bool) -> None:
    """Save translations to cache.
    
    Args:
        cache: CacheManager instance
        cache_key: Cache key to save under
        translations: List of translation dicts
        enable_cache: Whether caching is enabled
    """
    if enable_cache:
        cache.save_json(cache_key, translations)


def map_translations_to_segments(segments: List[Segment], 
                                  translations: List[Dict[str, str]]) -> List[Segment]:
    """Map parsed translations back to segments and check for missing IDs.
    
    Args:
        segments: Original list of Segment objects
        translations: Parsed translation list with 'id' and 'translated_text' keys
        
    Returns:
        List of Segment objects with target_text populated
        
    Raises:
        RuntimeError: If any segment ID is missing from translations
    """
    translation_map = {}
    for item in translations:
        translation_map[item["id"]] = item["translated_text"]
    
    for seg in segments:
        if seg.segment_id not in translation_map:
            logger.error(f"[Translate] Missing translation for segment {seg.segment_id}")
            raise RuntimeError("Fatal pipeline error")
        seg.target_text = translation_map[seg.segment_id]
    
    return segments


def format_friendly_error(provider_name: str, model: str, error: Exception) -> RuntimeError:
    """Format error message with friendly Chinese descriptions for common errors.
    
    Args:
        provider_name: Name of the provider (e.g., "NVIDIA", "OpenAI")
        model: Model name being used
        error: Original exception
        
    Returns:
        RuntimeError with friendly error message
    """
    err_msg = str(error)
    
    if "timeout" in err_msg.lower() or "timed out" in err_msg.lower():
        return RuntimeError(f"网络超时:{provider_name} API 响应超时。请检查网络连接或稍后重试。错误: {err_msg}")
    elif "401" in err_msg or "unauthorized" in err_msg.lower():
        return RuntimeError(f"认证失败:{provider_name} API Key 无效或已过期。请检查配置。错误: {err_msg}")
    elif "404" in err_msg or "not found" in err_msg.lower():
        return RuntimeError(f"模型不存在:配置的模型 '{model}' 在 {provider_name} API 上不可用。请检查模型名称。错误: {err_msg}")
    else:
        return RuntimeError(f"翻译失败:{err_msg}")
