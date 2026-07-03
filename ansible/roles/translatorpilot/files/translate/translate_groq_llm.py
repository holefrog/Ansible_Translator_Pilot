import logging
from .openai_compatible import OpenAICompatibleTranslate

logger = logging.getLogger("translate")

class GroqTranslate(OpenAICompatibleTranslate):
    def __init__(self, config: dict, retry_config: dict):
        super().__init__(config, retry_config)

    @property
    def name(self) -> str:
        return "groq"

    @property
    def base_url(self) -> str:
        return "https://api.groq.com/openai/v1/chat/completions"

    @property
    def headers(self) -> dict:
        api_key = self.config["api_key"]
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    @property
    def use_max_tokens(self) -> bool:
        return False


