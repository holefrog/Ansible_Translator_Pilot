from .openai_compatible import OpenAICompatibleTranslate


class GroqTranslate(OpenAICompatibleTranslate):
    @property
    def name(self) -> str:
        return "groq"

    @property
    def base_url(self) -> str:
        return "https://api.groq.com/openai/v1/chat/completions"

    @property
    def use_max_tokens(self) -> bool:
        return False
