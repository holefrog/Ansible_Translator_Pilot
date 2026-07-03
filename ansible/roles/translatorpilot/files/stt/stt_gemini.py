import os
import json
import logging
from typing import List
from contracts import Segment
from retry import with_retry
from .base import STTProvider

logger = logging.getLogger("stt")

class GeminiSTT(STTProvider):
    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config

    @property
    def name(self) -> str:
        return "gemini_stt"

    def transcribe(self, audio_path: str) -> List[Segment]:
        api_key = self.config["api_key"]
        model = self.config["model"]

        if not api_key:
            logger.error("[STT] Gemini API key is missing.")
            raise RuntimeError("Fatal pipeline error: Gemini API key is missing")

        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file to transcribe does not exist: {audio_path}")

        def run_api_call():
            import requests
            import base64
            
            # Use direct REST endpoint to allow standard lightweight execution
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            
            with open(audio_path, "rb") as f:
                audio_data = base64.b64encode(f.read()).decode("utf-8")
                
            custom_prompt = self.config.get("prompt")
            if not custom_prompt:
                logger.error("[STT] Prompt is missing from config.")
                raise RuntimeError("Fatal pipeline error")

            prompt = (
                f"{custom_prompt}\n\n"
                "Please transcribe this audio. Return a JSON array of transcription segments with timestamps. "
                "Each segment must contain 'start' (float seconds), 'end' (float seconds), and 'text' (string transcription)."
            )
            
            payload = {
                "contents": [{
                    "parts": [
                        {"inlineData": {"mimeType": "audio/mp3", "data": audio_data}},
                        {"text": prompt}
                    ]
                }],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseSchema": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "start": {"type": "NUMBER", "description": "Start time in seconds"},
                                "end": {"type": "NUMBER", "description": "End time in seconds"},
                                "text": {"type": "STRING", "description": "English transcript text"}
                            },
                            "required": ["start", "end", "text"]
                        }
                    }
                }
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=int(self.config.get("timeout", 90)))
            if response.status_code != 200:
                raise Exception(f"Gemini API Error {response.status_code}: {response.text}")
                
            resp_data = response.json()
            candidate_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
            parsed_data = json.loads(candidate_text)
            
            return [
                Segment(
                    start=float(item["start"]),
                    end=float(item["end"]),
                    source_text=item["text"].strip()
                )
                for item in parsed_data
            ]

        try:
            return with_retry(run_api_call, self.retry_config, "GeminiSTT")
        except ImportError:
            logger.error("[STT] 'requests' library not found. Run 'pip install requests'.")
            raise RuntimeError("Fatal pipeline error: missing dependencies")
