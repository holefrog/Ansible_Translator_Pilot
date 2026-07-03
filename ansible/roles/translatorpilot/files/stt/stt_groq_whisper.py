import logging
from typing import List
from contracts import Segment
from retry import with_retry
from .base import STTProvider
from .common import validate_api_key, validate_audio_file

logger = logging.getLogger("stt")

class GroqWhisperSTT(STTProvider):
    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config

    @property
    def name(self) -> str:
        return "groq_whisper"

    def transcribe(self, audio_path: str) -> List[Segment]:
        api_key = self.config["api_key"]
        model = self.config["model"]

        validate_api_key(api_key, "Groq")
        validate_audio_file(audio_path)

        def run_api_call():
            import requests
            url = "https://api.groq.com/openai/v1/audio/transcriptions"
            headers = {
                "Authorization": f"Bearer {api_key}"
            }
            files = {
                "file": ("audio.mp3", open(audio_path, "rb"), "audio/mpeg")
            }
            prompt_text = self.config.get("prompt")
            if not prompt_text:
                logger.error("[STT] Prompt is missing from config.")
                raise RuntimeError("Fatal pipeline error")

            data = {
                "model": model,
                "response_format": "verbose_json",
                "prompt": prompt_text
            }
            
            response = requests.post(url, headers=headers, files=files, data=data, timeout=int(self.config.get("timeout", 60)))
            if response.status_code != 200:
                raise Exception(f"Groq API Error {response.status_code}: {response.text}")
                
            result = response.json()
            segments_data = result.get("segments", [])
            
            if not segments_data:
                # Fallback in case of non-verbose format
                text = result.get("text", "No text transcribed")
                return [Segment(start=0.0, end=10.0, source_text=text)]
                
            return [
                Segment(
                    start=float(seg["start"]),
                    end=float(seg["end"]),
                    source_text=seg["text"].strip()
                )
                for seg in segments_data
            ]

        try:
            return with_retry(run_api_call, self.retry_config, "GroqWhisperSTT")
        except ImportError:
            logger.error("[STT] 'requests' library not found. Run 'pip install requests'.")
            raise RuntimeError("Fatal pipeline error: missing dependencies")


