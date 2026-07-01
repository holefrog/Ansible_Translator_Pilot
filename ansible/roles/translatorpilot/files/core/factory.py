from stt.groq_whisper import GroqWhisperSTT, GeminiSTT
from translate.gemini import GeminiTranslate
from tts.azure_speech import AzureSpeechTTS, GeminiTTS

class ProviderFactory:
    @staticmethod
    def create_stt(settings: dict):
        provider_name = settings.get("provider", {}).get("stt", "groq_whisper")
        retry_config = settings.get("retry", {})
        
        if provider_name == "groq_whisper":
            return GroqWhisperSTT(settings.get("stt", {}).get("groq_whisper", {}), retry_config)
        elif provider_name == "gemini_stt":
            return GeminiSTT(settings.get("stt", {}).get("gemini", {}), retry_config)
        else:
            print(f"[Factory] Unknown STT provider '{provider_name}'. Falling back to GroqWhisper.")
            return GroqWhisperSTT(settings.get("stt", {}).get("groq_whisper", {}), retry_config)

    @staticmethod
    def create_translate(settings: dict):
        provider_name = settings.get("provider", {}).get("translate", "gemini")
        retry_config = settings.get("retry", {})
        
        if provider_name == "gemini":
            return GeminiTranslate(settings.get("translate", {}).get("gemini", {}), retry_config)
        else:
            print(f"[Factory] Unknown translate provider '{provider_name}'. Falling back to Gemini.")
            return GeminiTranslate(settings.get("translate", {}).get("gemini", {}), retry_config)

    @staticmethod
    def create_tts(settings: dict):
        provider_name = settings.get("provider", {}).get("tts", "azure_speech")
        retry_config = settings.get("retry", {})
        
        if provider_name == "azure_speech":
            return AzureSpeechTTS(settings.get("tts", {}).get("azure_speech", {}), retry_config)
        elif provider_name == "gemini_tts":
            return GeminiTTS(retry_config)
        else:
            print(f"[Factory] Unknown TTS provider '{provider_name}'. Falling back to AzureSpeech.")
            return AzureSpeechTTS(settings.get("tts", {}).get("azure_speech", {}), retry_config)
