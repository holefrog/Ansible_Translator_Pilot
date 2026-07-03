import logging
from typing import List, Dict, Any

from .batch_base import BatchedTranslateProvider

logger = logging.getLogger("translate")


class GeminiTranslate(BatchedTranslateProvider):
    @property
    def name(self) -> str:
        return "gemini"

    @property
    def provider_display_name(self) -> str:
        return "Gemini"

    def _fetch_translations(
        self, system_instruction: str, user_prompt: str, model: str
    ) -> List[Dict[str, Any]]:
        import requests

        api_key = self.config["api_key"]
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        headers = {"Content-Type": "application/json"}

        payload = {
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [{
                "parts": [{"text": user_prompt}]
            }],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": float(self.config.get("temperature", 0.3)),
            },
        }

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=int(self.config.get("timeout", 60)),
        )
        if response.status_code != 200:
            raise Exception(f"Gemini API Error {response.status_code}: {response.text}")

        resp_data = response.json()
        try:
            candidate_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
            return self._parse_translation_json(candidate_text)
        except (KeyError, IndexError) as e:
            logger.error(f"Failed to parse Gemini JSON: {resp_data}")
            raise Exception(f"Gemini output is not valid JSON: {e}") from e
