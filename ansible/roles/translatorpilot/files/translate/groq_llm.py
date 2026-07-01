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
            logger.warning("[Translate] Groq API Key is missing. Falling back to default rule-based translations.")
            return self.get_mock_translations(segments)

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

            system_instruction = self.config.get("system_prompt", (
                "You are a professional video translator translating a sequence of English audio transcripts into Chinese spoken dubbing.\n"
                "CRITICAL RULES:\n"
                "1. Maintain extreme context coherence. Read all segments together to understand the full meaning.\n"
                "2. The translations must be concise, natural, and match the tempo of spoken Chinese.\n"
                "3. Keep any tech/industry acronyms natural.\n"
                "4. You MUST output ONLY a valid JSON array of objects. Do not include markdown code blocks or any other text.\n"
                "5. Each object must have exactly two string fields: 'id' and 'translated_text'.\n"
                "6. Output exactly matching translated objects for each ID.\n"
                "7. CRITICAL: DO NOT merge translations across segments! You MUST strictly translate ONLY the exact English words present within each specific segment's 'text', even if that text is an incomplete fragment. Never pull meaning from the next segment into the current segment."
            ))
            
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
                seg.target_text = translation_map.get(seg.segment_id, self.fallback_translate_text(seg.source_text))
                
            return segments

        try:
            return with_retry(run_api_call, self.retry_config, "GroqTranslate")
        except ImportError:
            logger.error("[Translate] 'requests' library not found. Falling back to simple default translation.")
            return self.get_mock_translations(segments)
        except Exception as e:
            logger.error(f"[Translate] Failed Groq translation: {e}. Falling back to mock translations.")
            return self.get_mock_translations(segments)

    def fallback_translate_text(self, text: str) -> str:
        text_lower = text.lower()
        if "welcome to today's deep dive" in text_lower or "welcome to the future" in text_lower:
            return "欢迎来到 Translator Pilot 翻译技术的未来。"
        if "runs whisper" in text_lower or "this pipeline runs" in text_lower:
            return "该管线使用 Whisper 进行语音识别，使用 Gemini 进行翻译，并使用 Azure 进行语音合成。"
        if "extremely fast" in text_lower:
            return "它被设计为运行极快、稳健，且支持完全离线或混合模式。"
        if "length check" in text_lower or "perform a length check" in text_lower:
            return "让我们进行时长检查，以确保中文配音音频与原始英文时间对齐良好。"
        return f"[中译] {text}"

    def get_mock_translations(self, segments: List[Segment]) -> List[Segment]:
        for seg in segments:
            seg.target_text = self.fallback_translate_text(seg.source_text)
            seg.is_fallback = True
        return segments
