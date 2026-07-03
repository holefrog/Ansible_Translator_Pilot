import logging
import wave
from contracts import Segment
from .http_rate_limited import HTTPRateLimitedTTS
from cache import CacheManager
from .common import wrap_pcm_as_wav

logger = logging.getLogger("tts")

# NVIDIA Magpie TTS Multilingual HTTP endpoint
# Supports: en-US, zh-CN, es-ES, fr-FR, de-DE, ja-JP, hi-IN, it-IT, vi-VN
NVIDIA_MAGPIE_TTS_URL = (
    "https://877104f7-e885-42b9-8de8-f6e4c6303969"
    ".invocation.api.nvcf.nvidia.com/v1/audio/synthesize"
)

class NvidiaMagpieTTS(HTTPRateLimitedTTS):
    """TTS provider using NVIDIA Magpie Multilingual model via Riva HTTP API.
    
    Supports Chinese (zh-CN) and many other languages.
    Voice format: Magpie-Multilingual.ZH-CN.<VoiceName>
    Common Chinese voices: Aria, Diego, HouZhen, Isabela, Long, Louise, Mia, Pascal, Ray, Siwei
    """

    def __init__(self, config: dict, retry_config: dict):
        super().__init__(config, retry_config)
        
        self.language = self.config.get("language", "zh-CN")
        self.voice = self.config.get("voice", "Magpie-Multilingual.ZH-CN.Aria")
        self.sample_rate = int(self.config.get("sample_rate_hz", 44100))

    @property
    def name(self) -> str:
        return "nvidia_magpie_tts"

    def build_cache_key(self, segment: Segment) -> str:
        cache = CacheManager("wav", "")
        return cache.get_cache_key(segment.target_text, self.voice, self.language, self.sample_rate)

    def synthesize_audio(self, segment: Segment, output_path: str) -> None:
        import requests
        
        api_key = self.config["api_key"]
        
        headers = {
            "Authorization": f"Bearer {api_key}"
        }

        # NVIDIA Riva HTTP TTS uses form data
        data = {
            "text": segment.target_text,
            "language": self.language,
            "voice": self.voice,
            "encoding": "LINEAR_PCM",
            "sample_rate_hz": str(self.sample_rate)
        }

        response = requests.post(
            NVIDIA_MAGPIE_TTS_URL,
            headers=headers,
            data=data,
            timeout=int(self.config.get("timeout", 60))
        )

        if response.status_code != 200:
            raise Exception(
                f"NVIDIA Magpie TTS API Error {response.status_code}: {response.text}"
            )

        # Response is raw PCM audio — wrap it in a WAV container
        pcm_data = response.content
        wrap_pcm_as_wav(pcm_data, output_path, sample_rate=self.sample_rate)
