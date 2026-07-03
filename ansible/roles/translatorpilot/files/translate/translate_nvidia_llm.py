import logging
from .openai_compatible import OpenAICompatibleTranslate

logger = logging.getLogger("translate")

class NvidiaTranslate(OpenAICompatibleTranslate):
    """Translation provider using NVIDIA NIM API (OpenAI-compatible).
    
    Uses meta/llama-3.1-70b-instruct (or any other NIM-hosted model) via
    the NVIDIA NIM base URL: https://integrate.api.nvidia.com/v1
    """

    def __init__(self, config: dict, retry_config: dict):
        super().__init__(config, retry_config)

    @property
    def name(self) -> str:
        return "nvidia_llm"

    @property
    def base_url(self) -> str:
        return "https://integrate.api.nvidia.com/v1/chat/completions"

    @property
    def headers(self) -> dict:
        api_key = self.config["api_key"]
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    @property
    def use_response_format(self) -> bool:
        return False

    @property
    def timeout(self) -> int:
        return 120

    @property
    def additional_system_instruction(self) -> str:
        return "CRITICAL: Keep translations concise and natural. DO NOT repeat words."

    @property
    def provider_display_name(self) -> str:
        return "NVIDIA LLM"
