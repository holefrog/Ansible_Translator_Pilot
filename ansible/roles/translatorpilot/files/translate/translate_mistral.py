from .openai_compatible import OpenAICompatibleTranslate


class MistralTranslate(OpenAICompatibleTranslate):
    @property
    def name(self) -> str:
        return "mistral"

    @property
    def base_url(self) -> str:
        return "https://api.mistral.ai/v1/chat/completions"

    @property
    def provider_display_name(self) -> str:
        return "Mistral"
