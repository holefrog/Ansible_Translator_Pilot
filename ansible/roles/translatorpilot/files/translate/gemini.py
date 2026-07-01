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

        api_key = self.config.get("api_key") or os.environ.get("GEMINI_API_KEY")
        model = self.config.get("model", "gemini-3.5-flash")

        if not api_key:
            logger.error("[Translate] Gemini API Key is missing. Cannot proceed.")
            import sys
            sys.exit(1)

        def run_api_call():
            import requests
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            
            items_to_translate = [
                {"id": seg.segment_id, "text": seg.source_text}
                for seg in segments
            ]
            
            system_instruction = self.config.get("system_prompt")
            if not system_instruction:
                logger.error("[Translate] System prompt is missing from config.")
                import sys
                sys.exit(1)

            user_instruction = self.config.get("user_prompt")
            if not user_instruction:
                logger.error("[Translate] User prompt is missing from config.")
                import sys
                sys.exit(1)

            user_prompt = f"{user_instruction}\n{json.dumps(items_to_translate, indent=2)}"
            
            import hashlib
            import os

            cache_dir = os.path.join(os.getcwd(), "cache", "translate")
            os.makedirs(cache_dir, exist_ok=True)
            
            cache_string = system_instruction + user_prompt + model
            cache_key = hashlib.md5(cache_string.encode("utf-8")).hexdigest()
            cache_filepath = os.path.join(cache_dir, f"{cache_key}.json")

            if os.path.exists(cache_filepath):
                logger.info("[Translate] Translation cache hit!")
                with open(cache_filepath, "r", encoding="utf-8") as f:
                    parsed_translations = json.load(f)
            else:
                payload = {
                    "contents": [{
                        "parts": [{"text": user_prompt}]
                    }],
                    "systemInstruction": {
                        "parts": [{"text": system_instruction}]
                    },
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseSchema": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "id": {"type": "STRING", "description": "The segment_id matching input"},
                                    "translated_text": {"type": "STRING", "description": "Natural Chinese translation"}
                                },
                                "required": ["id", "translated_text"]
                            }
                        }
                    }
                }

                response = requests.post(url, headers=headers, json=payload, timeout=60)
                if response.status_code != 200:
                    raise Exception(f"Gemini Translate API Error {response.status_code}: {response.text}")

                resp_data = response.json()
                candidate_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
                parsed_translations = json.loads(candidate_text)
                with open(cache_filepath, "w", encoding="utf-8") as f:
                    json.dump(parsed_translations, f, ensure_ascii=False)
            
            translation_map = {item["id"]: item["translated_text"] for item in parsed_translations}
            
            for seg in segments:
                if seg.segment_id not in translation_map:
                    logger.error(f"[Translate] Missing translation for segment {seg.segment_id}")
                    import sys
                    sys.exit(1)
                seg.target_text = translation_map[seg.segment_id]

            return segments

        try:
            return with_retry(run_api_call, self.retry_config, "GeminiTranslate")
        except ImportError:
            logger.error("[Translate] 'requests' library not found.")
            import sys
            sys.exit(1)
        except Exception as e:
            logger.error(f"[Translate] Failed Gemini translation: {e}.")
            import sys
            sys.exit(1)
