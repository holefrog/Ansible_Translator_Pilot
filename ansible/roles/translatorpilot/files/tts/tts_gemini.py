import logging
import time
import wave
import io
import base64
from contracts import Segment
from .http_rate_limited import HTTPRateLimitedTTS
from cache import CacheManager
from .common import wrap_pcm_as_wav

logger = logging.getLogger("tts")

class GeminiTTS(HTTPRateLimitedTTS):
    def __init__(self, config: dict, retry_config: dict):
        super().__init__(config, retry_config)
        
        api_key = self.config["api_key"]
        if not api_key:
            logger.error("[TTS] Gemini API Key is missing for TTS. Cannot proceed.")
            raise RuntimeError("Fatal pipeline error")

    @property
    def name(self) -> str:
        return "gemini_tts"

    def build_cache_key(self, segment: Segment) -> str:
        cache = CacheManager("wav", "")
        voice = self.config["voice"]
        return cache.get_cache_key(segment.target_text, voice)

    def synthesize_audio(self, segment: Segment, output_path: str) -> None:
        import requests
        
        api_key = self.config["api_key"]
        model = self.config["model"]
        voice = self.config["voice"]
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}

        payload = {
            "contents": [{
                "parts": [{"text": f"Read this in natural Chinese: {segment.target_text}"}]
            }],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": voice
                        }
                    }
                }
            }
        }

        # Gemini has a separate 3 RPM rate limit that needs special handling
        max_rate_retries = 10
        for attempt in range(max_rate_retries):
            response = requests.post(url, headers=headers, json=payload, timeout=int(self.config.get("timeout", 30)))
            if response.status_code == 429:
                delay = 30
                try:
                    err_data = response.json()
                    for detail in err_data.get("error", {}).get("details", []):
                        if "retryDelay" in detail:
                            delay = int(detail["retryDelay"].replace("s", "")) + 1
                except Exception:
                    pass
                
                logger.warning(f"[TTS] Gemini API rate limit (3 RPM) hit. Sleeping for {delay} seconds before retry...")
                time.sleep(delay)
                continue
                
            if response.status_code != 200:
                raise Exception(f"Gemini TTS API Error {response.status_code}: {response.text}")
            break
        else:
            raise Exception("Gemini TTS API Error: Exceeded max retries for rate limit (429)")

        resp_data = response.json()
        base64_audio = resp_data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        pcm_data = base64.b64decode(base64_audio)
        
        # Gemini TTS returns raw PCM (24kHz, 16-bit, mono). Wrap in WAV container.
        wrap_pcm_as_wav(pcm_data, output_path, sample_rate=24000)
