import os
import json
import logging
from typing import List
from contracts import Segment
from retry import with_retry
from .base import TranslateProvider
from cache import CacheManager
from .common import (
    strip_markdown_fences,
    build_system_prompt,
    build_user_prompt,
    get_cache_key,
    check_cache,
    load_from_cache,
    save_to_cache,
    map_translations_to_segments,
    format_friendly_error
)

logger = logging.getLogger("translate")

class GeminiTranslate(TranslateProvider):
    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config

    @property
    def name(self) -> str:
        return "gemini"

    def translate(self, segments: List[Segment]) -> List[Segment]:
        if not segments:
            return []

        api_key = self.config["api_key"]
        model = self.config["model"]

        if not api_key:
            logger.error("[Translate] Gemini API Key is missing. Cannot proceed.")
            raise RuntimeError("Fatal pipeline error")

        def run_api_call():
            import requests

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            headers = {
                "Content-Type": "application/json"
            }

            cache = CacheManager("translate", os.getcwd())
            enable_cache = self.config.get("enable_cache", False)
            batch_size = int(self.config.get("batch_size", 20))

            for i in range(0, len(segments), batch_size):
                batch = segments[i:i+batch_size]
                items_to_translate = [
                    {"id": seg.segment_id, "text": seg.source_text}
                    for seg in batch
                ]

                # Build prompts using common utilities
                base_system_instruction, system_instruction = build_system_prompt(
                    self.config, len(items_to_translate)
                )
                user_prompt = build_user_prompt(self.config, items_to_translate)
                cache_key = get_cache_key(cache, base_system_instruction, user_prompt, model)

                # Check cache
                if check_cache(cache, cache_key, enable_cache):
                    logger.info(f"[Translate] Translation cache hit for batch {i//batch_size + 1}!")
                    parsed_translations = load_from_cache(cache, cache_key)
                else:
                    # Build Gemini-specific payload
                    payload = {
                        "systemInstruction": {
                            "parts": [{"text": system_instruction}]
                        },
                        "contents": [{
                            "parts": [{"text": user_prompt}]
                        }],
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "temperature": float(self.config.get("temperature", 0.3))
                        }
                    }

                    response = requests.post(url, headers=headers, json=payload, timeout=int(self.config.get("timeout", 60)))
                    if response.status_code != 200:
                        raise Exception(f"Gemini API Error {response.status_code}: {response.text}")

                    resp_data = response.json()
                    
                    try:
                        candidate_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
                        # Strip markdown fences (now applied to all providers)
                        candidate_text = strip_markdown_fences(candidate_text)
                        parsed_json = json.loads(candidate_text)
                        parsed_translations = parsed_json.get("translations", [])
                        save_to_cache(cache, cache_key, parsed_translations, enable_cache)
                    except (KeyError, IndexError, json.JSONDecodeError) as e:
                        logger.error(f"Failed to parse Gemini JSON: {resp_data}")
                        raise Exception(f"Gemini output is not valid JSON: {e}")

                # Map translations back to segments using common utility
                map_translations_to_segments(batch, parsed_translations)

            return segments

        try:
            return with_retry(run_api_call, self.retry_config, "GeminiTranslate")
        except ImportError:
            logger.error("[Translate] 'requests' library not found.")
            raise RuntimeError("Fatal pipeline error")
        except Exception as e:
            logger.error(f"[Translate] Failed Gemini translation: {e}.")
            raise format_friendly_error("Gemini", model, e)
