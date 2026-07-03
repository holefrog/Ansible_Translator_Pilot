from .openai_compatible import OpenAICompatibleTranslate


class OpenAITranslate(OpenAICompatibleTranslate):
    @property
    def name(self) -> str:
        return "openai"

    @property
    def base_url(self) -> str:
        return "https://api.openai.com/v1/chat/completions"

    @property
    def provider_display_name(self) -> str:
        return "OpenAI"
