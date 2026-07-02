import os
import json
import logging
from typing import List
from contracts import Segment
from retry import with_retry
from .base import TranslateProvider
from cache import CacheManager

logger = logging.getLogger("translate")

class NvidiaTranslate(TranslateProvider):
    """Translation provider using NVIDIA NIM API (OpenAI-compatible).
    
    Uses meta/llama-3.1-70b-instruct (or any other NIM-hosted model) via
    the NVIDIA NIM base URL: https://integrate.api.nvidia.com/v1
    """

    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config

    @property
    def name(self) -> str:
        return "nvidia_llm"

    def translate(self, segments: List[Segment]) -> List[Segment]:
        if not segments:
            return []

        api_key = self.config["api_key"]
        model = self.config["model"]

        if not api_key:
            logger.error("[Translate] NVIDIA API Key is missing. Cannot proceed.")
            raise RuntimeError("Fatal pipeline error")

        def run_api_call():
            import requests
            import hashlib

            # NVIDIA NIM uses a standard OpenAI-compatible endpoint
            url = "https://integrate.api.nvidia.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            # 使用统一的缓存管理器
            cache = CacheManager("translate", os.getcwd())

            translation_map = {}
            batch_size = 20

            for i in range(0, len(segments), batch_size):
                batch = segments[i:i + batch_size]
                items_to_translate = [
                    {"id": seg.segment_id, "text": seg.source_text}
                    for seg in batch
                ]

                system_instruction = self.config["system_prompt"]
                if not system_instruction:
                    logger.error("[Translate] System prompt is missing from config.")
                    raise RuntimeError("Fatal pipeline error")

                system_instruction += "\nOutput JSON format: {\"translations\": [{\"id\": \"...\", \"translated_text\": \"...\"}]}"
                system_instruction += f"\nCRITICAL: You are given {len(items_to_translate)} segments. Your JSON array MUST contain exactly {len(items_to_translate)} items. DO NOT skip any IDs."
                system_instruction += "\nCRITICAL: Output raw UTF-8 Chinese characters. DO NOT use \\uXXXX unicode escaping."
                system_instruction += "\nCRITICAL: Keep translations concise and natural. DO NOT repeat words."

                user_instruction = self.config["user_prompt"]
                if not user_instruction:
                    logger.error("[Translate] User prompt is missing from config.")
                    raise RuntimeError("Fatal pipeline error")

                user_prompt = f"{user_instruction}\n{json.dumps(items_to_translate, indent=2)}"

                # 生成缓存 key
                cache_key = cache.get_cache_key(system_instruction, user_prompt, model)

                if cache.exists(cache_key, ".json"):
                    logger.info(f"[Translate] Translation cache hit for batch {i // batch_size + 1}!")
                    parsed_translations = cache.load_json(cache_key)
                else:
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 2048
                    }

                    response = requests.post(url, headers=headers, json=payload, timeout=120)
                    if response.status_code != 200:
                        raise Exception(f"NVIDIA LLM Translate API Error {response.status_code}: {response.text}")

                    resp_data = response.json()
                    candidate_text = resp_data["choices"][0]["message"]["content"]

                    try:
                        parsed_json = json.loads(candidate_text)
                        parsed_translations = parsed_json.get("translations", [])
                        cache.save_json(cache_key, parsed_translations)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse NVIDIA LLM JSON: {candidate_text}")
                        raise Exception(f"NVIDIA LLM Translate output is not valid JSON: {e}")

                for item in parsed_translations:
                    translation_map[item["id"]] = item["translated_text"]

            for seg in segments:
                if seg.segment_id not in translation_map:
                    logger.error(f"[Translate] Missing translation for segment {seg.segment_id}")
                    raise RuntimeError("Fatal pipeline error")
                seg.target_text = translation_map[seg.segment_id]

            return segments

        try:
            return with_retry(run_api_call, self.retry_config, "NvidiaTranslate")
        except ImportError:
            logger.error("[Translate] 'requests' library not found.")
            raise RuntimeError("Fatal pipeline error: requests library missing")
        except Exception as e:
            err_msg = str(e)
            logger.error(f"[Translate] Failed NVIDIA LLM translation: {err_msg}.")
            # 提供更详细的错误信息
            if "timeout" in err_msg.lower() or "timed out" in err_msg.lower():
                raise RuntimeError(f"网络超时：NVIDIA API 响应超时。请检查网络连接或稍后重试。错误: {err_msg}")
            elif "401" in err_msg or "unauthorized" in err_msg.lower():
                raise RuntimeError(f"认证失败：NVIDIA API Key 无效或已过期。请检查配置。错误: {err_msg}")
            elif "404" in err_msg or "not found" in err_msg.lower():
                raise RuntimeError(f"模型不存在：配置的模型 '{model}' 在 NVIDIA API 上不可用。请检查模型名称。错误: {err_msg}")
            else:
                raise RuntimeError(f"翻译失败：{err_msg}")
