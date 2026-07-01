import os
import json
import logging
from typing import List
from contracts import Segment
from retry import with_retry
from .base import TranslateProvider

logger = logging.getLogger("translate")

class GroqTranslate(TranslateProvider):
    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config

    @property
    def name(self) -> str:
        return "groq"

    def translate(self, segments: List[Segment]) -> List[Segment]:
        if not segments:
            return []

        api_key = self.config.get("api_key") or os.environ.get("GROQ_API_KEY")
        model = self.config.get("model", "llama3-70b-8192")

        if not api_key:
            logger.error("[Translate] Groq API Key is missing. Cannot proceed.")
            import sys
            sys.exit(1)

        def run_api_call():
            import requests
            
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            items_to_translate = [
                {"id": seg.segment_id, "text": seg.source_text}
                for seg in segments
            ]

            system_instruction = self.config.get("system_prompt")
            if not system_instruction:
                logger.error("[Translate] System prompt is missing from config.")
                import sys
                sys.exit(1)
            
            system_instruction += "\nOutput JSON format: {\"translations\": [{\"id\": \"...\", \"translated_text\": \"...\"}]}"

            user_prompt = f"Please translate these segments and return ONLY JSON:\n{json.dumps(items_to_translate, indent=2)}"

            import hashlib
            import os
            
            # Use output_dir parameter to resolve cache dir (assuming we are in a pipeline, we need to locate cache dir)
            # We can use os.getcwd() + /cache/translate or similar.
            # But we don't have output_dir in this method. We can use a global or relative path.
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
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": user_prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.3
                }

                response = requests.post(url, headers=headers, json=payload, timeout=60)
                if response.status_code != 200:
                    raise Exception(f"Groq Translate API Error {response.status_code}: {response.text}")

                resp_data = response.json()
                candidate_text = resp_data["choices"][0]["message"]["content"]

                try:
                    parsed_json = json.loads(candidate_text)
                    parsed_translations = parsed_json.get("translations", [])
                    with open(cache_filepath, "w", encoding="utf-8") as f:
                        json.dump(parsed_translations, f, ensure_ascii=False)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse Groq JSON: {candidate_text}")
                    raise Exception(f"Groq Translate output is not valid JSON: {e}")

            translation_map = {item["id"]: item["translated_text"] for item in parsed_translations}
            
            for seg in segments:
                if seg.segment_id not in translation_map:
                    logger.error(f"[Translate] Missing translation for segment {seg.segment_id}")
                    import sys
                    sys.exit(1)
                seg.target_text = translation_map[seg.segment_id]

            return segments

        try:
            return with_retry(run_api_call, self.retry_config, "GroqTranslate")
        except ImportError:
            logger.error("[Translate] 'requests' library not found.")
            import sys
            sys.exit(1)
        except Exception as e:
            logger.error(f"[Translate] Failed Groq translation: {e}.")
            import sys
            sys.exit(1)


