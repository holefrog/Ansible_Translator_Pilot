import json
import logging
from typing import List, Dict, Any

from http_utils import bearer_json_headers
from .batch_base import BatchedTranslateProvider

logger = logging.getLogger("translate")


class OpenAICompatibleTranslate(BatchedTranslateProvider):
    """Base class for OpenAI-compatible translation providers.

  Subclasses override base_url and optional API behavior properties.
    """

    @property
    def base_url(self) -> str:
        raise NotImplementedError("Subclass must implement base_url")

    @property
    def headers(self) -> dict:
        return bearer_json_headers(self.config["api_key"])

    @property
    def use_response_format(self) -> bool:
        return True

    @property
    def use_max_tokens(self) -> bool:
        return True

    @property
    def timeout(self) -> int:
        return 60

    def _fetch_translations(
        self, system_instruction: str, user_prompt: str, model: str
    ) -> List[Dict[str, Any]]:
        import requests

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": float(self.config.get("temperature", 0.3)),
        }

        if self.use_response_format:
            payload["response_format"] = {"type": "json_object"}

        if self.use_max_tokens:
            payload["max_tokens"] = int(self.config.get("max_tokens", 4096))

        response = requests.post(
            self.base_url,
            headers=self.headers,
            json=payload,
            timeout=self.timeout,
        )

        if response.status_code != 200:
            raise Exception(
                f"{self.provider_display_name} API Error {response.status_code}: {response.text}"
            )

        resp_data = response.json()
        candidate_text = resp_data["choices"][0]["message"]["content"]
        return self._parse_translation_json(candidate_text)
