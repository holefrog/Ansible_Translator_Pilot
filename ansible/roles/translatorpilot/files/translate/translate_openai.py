import os
import json
import logging
from typing import List
from contracts import Segment
from retry import with_retry
from .base import TranslateProvider
from cache import CacheManager

logger = logging.getLogger("translate")

class OpenAITranslate(TranslateProvider):
    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config

    @property
    def name(self) -> str:
        return "openai"

    def translate(self, segments: List[Segment]) -> List[Segment]:
        if not segments:
            return []

        api_key = self.config["api_key"]
        model = self.config["model"]

        if not api_key:
            logger.error("[Translate] OpenAI API Key is missing. Cannot proceed.")
            raise RuntimeError("Fatal pipeline error")

        def run_api_call():
            import requests

            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }

            # 使用统一的缓存管理器
            cache = CacheManager("translate", os.getcwd())
            enable_cache = self.config.get("enable_cache", False)

            translation_map = {}
            batch_size = int(self.config.get("batch_size", 20))

            for i in range(0, len(segments), batch_size):
                batch = segments[i:i+batch_size]
                items_to_translate = [
                    {"id": seg.segment_id, "text": seg.source_text}
                    for seg in batch
                ]

                system_instruction = self.config["system_prompt"]
                if not system_instruction:
                    logger.error("[Translate] System prompt is missing from config.")
                    raise RuntimeError("Fatal pipeline error")

                # 使用原始 system_prompt 生成缓存 key（避免动态内容影响缓存）
                base_system_instruction = self.config["system_prompt"]

                system_instruction += "\nOutput JSON format: {\"translations\": [{\"id\": \"...\", \"translated_text\": \"...\"}]}"
                system_instruction += f"\nCRITICAL: You are given {len(items_to_translate)} segments. Your JSON array MUST contain exactly {len(items_to_translate)} items. DO NOT skip any IDs."
                system_instruction += "\nCRITICAL: Output raw UTF-8 Chinese characters. DO NOT use \\uXXXX unicode escaping."

                user_instruction = self.config["user_prompt"]
                if not user_instruction:
                    logger.error("[Translate] User prompt is missing from config.")
                    raise RuntimeError("Fatal pipeline error")

                user_prompt = f"{user_instruction}\n{json.dumps(items_to_translate, indent=2)}"

                # 生成缓存 key（使用稳定的参数）
                cache_key = cache.get_cache_key(base_system_instruction, user_prompt, model)

                if enable_cache and cache.exists(cache_key, ".json"):
                    logger.info(f"[Translate] Translation cache hit for batch {i//batch_size + 1}!")
                    parsed_translations = cache.load_json(cache_key)
                else:
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": user_prompt}
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": float(self.config.get("temperature", 0.3)),
                        "max_tokens": int(self.config.get("max_tokens", 4096))
                    }

                    response = requests.post(url, headers=headers, json=payload, timeout=int(self.config.get("timeout", 60)))
                    if response.status_code != 200:
                        raise Exception(f"OpenAI API Error {response.status_code}: {response.text}")

                    resp_data = response.json()
                    candidate_text = resp_data["choices"][0]["message"]["content"]

                    try:
                        parsed_json = json.loads(candidate_text)
                        parsed_translations = parsed_json.get("translations", [])
                        if enable_cache:
                            cache.save_json(cache_key, parsed_translations)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse OpenAI JSON: {candidate_text}")
                        raise Exception(f"OpenAI output is not valid JSON: {e}")

                for item in parsed_translations:
                    translation_map[item["id"]] = item["translated_text"]

            for seg in segments:
                if seg.segment_id not in translation_map:
                    logger.error(f"[Translate] Missing translation for segment {seg.segment_id}")
                    raise RuntimeError("Fatal pipeline error")
                seg.target_text = translation_map[seg.segment_id]

            return segments

        try:
            return with_retry(run_api_call, self.retry_config, "OpenAITranslate")
        except ImportError:
            logger.error("[Translate] 'requests' library not found.")
            raise RuntimeError("Fatal pipeline error")
        except Exception as e:
            logger.error(f"[Translate] Failed OpenAI translation: {e}.")
            raise RuntimeError("Fatal pipeline error")
