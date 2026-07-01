import os
import json
import logging
from typing import List
from contracts import Segment
from retry import with_retry
from .base import TranslateProvider

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
            import hashlib
            import os

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            headers = {
                "Content-Type": "application/json"
            }

            cache_dir = os.path.join(os.getcwd(), "cache", "translate")
            os.makedirs(cache_dir, exist_ok=True)

            translation_map = {}
            batch_size = 20

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

                system_instruction += "\nOutput JSON format: {\"translations\": [{\"id\": \"...\", \"translated_text\": \"...\"}]}"
                system_instruction += f"\nCRITICAL: You are given {len(items_to_translate)} segments. Your JSON array MUST contain exactly {len(items_to_translate)} items. DO NOT skip any IDs."
                system_instruction += "\nCRITICAL: Output raw UTF-8 Chinese characters. DO NOT use \\uXXXX unicode escaping."

                user_instruction = self.config["user_prompt"]
                if not user_instruction:
                    logger.error("[Translate] User prompt is missing from config.")
                    raise RuntimeError("Fatal pipeline error")

                user_prompt = f"{user_instruction}\n{json.dumps(items_to_translate, indent=2)}"

                cache_string = system_instruction + user_prompt + model
                cache_key = hashlib.md5(cache_string.encode("utf-8")).hexdigest()
                cache_filepath = os.path.join(cache_dir, f"{cache_key}.json")

                if os.path.exists(cache_filepath):
                    logger.info(f"[Translate] Translation cache hit for batch {i//batch_size + 1}!")
                    with open(cache_filepath, "r", encoding="utf-8") as f:
                        parsed_translations = json.load(f)
                else:
                    payload = {
                        "systemInstruction": {
                            "parts": [{"text": system_instruction}]
                        },
                        "contents": [{
                            "parts": [{"text": user_prompt}]
                        }],
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "temperature": 0.3
                        }
                    }

                    response = requests.post(url, headers=headers, json=payload, timeout=60)
                    if response.status_code != 200:
                        raise Exception(f"Gemini API Error {response.status_code}: {response.text}")

                    resp_data = response.json()
                    
                    try:
                        candidate_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
                        parsed_json = json.loads(candidate_text)
                        parsed_translations = parsed_json.get("translations", [])
                        with open(cache_filepath, "w", encoding="utf-8") as f:
                            json.dump(parsed_translations, f, ensure_ascii=False)
                    except (KeyError, IndexError, json.JSONDecodeError) as e:
                        logger.error(f"Failed to parse Gemini JSON: {resp_data}")
                        raise Exception(f"Gemini output is not valid JSON: {e}")

                for item in parsed_translations:
                    translation_map[item["id"]] = item["translated_text"]

            for seg in segments:
                if seg.segment_id not in translation_map:
                    logger.error(f"[Translate] Missing translation for segment {seg.segment_id}")
                    raise RuntimeError("Fatal pipeline error")
                seg.target_text = translation_map[seg.segment_id]

            return segments

        try:
            return with_retry(run_api_call, self.retry_config, "GeminiTranslate")
        except ImportError:
            logger.error("[Translate] 'requests' library not found.")
            raise RuntimeError("Fatal pipeline error")
        except Exception as e:
            logger.error(f"[Translate] Failed Gemini translation: {e}.")
            raise RuntimeError("Fatal pipeline error")
