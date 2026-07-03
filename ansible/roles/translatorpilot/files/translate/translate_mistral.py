from .openai_compatible import OpenAICompatibleTranslate


class MistralTranslate(OpenAICompatibleTranslate):
    """
    基于 Mistral AI 接口的大模型翻译提供商。
    兼容 OpenAI API 规范。
    """
    @property
    def name(self) -> str:
        return "mistral"

    @property
    def base_url(self) -> str:
        return "https://api.mistral.ai/v1/chat/completions"

    @property
    def provider_display_name(self) -> str:
        return "Mistral"
