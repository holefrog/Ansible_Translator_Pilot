import logging
from typing import List

from contracts import Segment
from http_utils import bearer_headers
from .http_base import HTTPSTTProvider
from .common import segments_from_groq_response

logger = logging.getLogger("stt")


class GroqWhisperSTT(HTTPSTTProvider):
    """
    基于 Groq 云端托管的 Whisper 模型的语音识别 (STT) 提供商。
    提供快速的 OpenAI 兼容 API 音频转录能力。
    """
    @property
    def name(self) -> str:
        return "groq_whisper"

    def _call_api(self, audio_path: str) -> List[Segment]:
        import requests

        api_key = self.config["api_key"]
        model = self.config["model"]
        prompt_text = self.config["prompt"]

        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = bearer_headers(api_key)
        files = {
            "file": ("audio.mp3", open(audio_path, "rb"), "audio/mpeg")
        }
        data = {
            "model": model,
            "response_format": "verbose_json",
            "prompt": prompt_text,
        }

        response = requests.post(
            url,
            headers=headers,
            files=files,
            data=data,
            timeout=int(self.config.get("timeout", 60)),
        )
        if response.status_code != 200:
            raise Exception(f"Groq API Error {response.status_code}: {response.text}")

        return segments_from_groq_response(response.json())
