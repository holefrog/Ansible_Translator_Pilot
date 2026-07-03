from .openai_compatible import OpenAICompatibleTranslate


class NvidiaTranslate(OpenAICompatibleTranslate):
    """Translation provider using NVIDIA NIM API (OpenAI-compatible)."""

    @property
    def name(self) -> str:
        return "nvidia_llm"

    @property
    def base_url(self) -> str:
        return "https://integrate.api.nvidia.com/v1/chat/completions"

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
