from .openai_compatible import OpenAICompatibleTranslate


class GroqTranslate(OpenAICompatibleTranslate):
    """
    基于 Groq API 托管的开源大模型翻译提供商。
    兼容 OpenAI API 规范，拥有极高的推理速度。
    """
    @property
    def name(self) -> str:
        return "groq"

    @property
    def base_url(self) -> str:
        return "https://api.groq.com/openai/v1/chat/completions"

    @property
    def use_max_tokens(self) -> bool:
        return False
