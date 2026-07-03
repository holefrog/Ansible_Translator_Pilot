from .openai_compatible import OpenAICompatibleTranslate


class OpenAITranslate(OpenAICompatibleTranslate):
    """
    基于 OpenAI 官方 API 的大模型翻译提供商。
    支持 GPT-4o, GPT-4-turbo 等模型。
    """
    @property
    def name(self) -> str:
        return "openai"

    @property
    def base_url(self) -> str:
        return "https://api.openai.com/v1/chat/completions"

    @property
    def provider_display_name(self) -> str:
        return "OpenAI"
