import logging
from .openai_compatible import OpenAICompatibleTranslate

logger = logging.getLogger("translate")

class MistralTranslate(OpenAICompatibleTranslate):
    def __init__(self, config: dict, retry_config: dict):
        super().__init__(config, retry_config)

    @property
    def name(self) -> str:
        return "mistral"

    @property
    def base_url(self) -> str:
        return "https://api.mistral.ai/v1/chat/completions"

    @property
    def headers(self) -> dict:
        api_key = self.config["api_key"]
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

    @property
    def provider_display_name(self) -> str:
        return "Mistral"
