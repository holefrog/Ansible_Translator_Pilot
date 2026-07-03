import json
import logging
from typing import List, Dict, Any

from http_utils import bearer_json_headers
from .batch_base import BatchedTranslateProvider

logger = logging.getLogger("translate")


class OpenAICompatibleTranslate(BatchedTranslateProvider):
    """
    兼容 OpenAI Chat API 标准格式的翻译提供商基类。
    适用于包括 OpenAI, Groq, NVIDIA, Mistral 等遵循该规范的模型接口。
    
    子类需要覆盖 `base_url` 属性。
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
        with open("/home/david/translator-pilot/groq_debug.json", "w") as f:
            json.dump(resp_data, f, indent=2)
        candidate_text = resp_data["choices"][0]["message"].get("content", "")
        return self._parse_translation_json(candidate_text)
