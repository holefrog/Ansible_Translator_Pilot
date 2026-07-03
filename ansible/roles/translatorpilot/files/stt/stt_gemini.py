import json
import logging
from typing import List

from contracts import Segment
from .http_base import HTTPSTTProvider
from .common import segments_from_timestamps

logger = logging.getLogger("stt")


class GeminiSTT(HTTPSTTProvider):
    @property
    def name(self) -> str:
        return "gemini_stt"

    def _call_api(self, audio_path: str) -> List[Segment]:
        import requests
        import base64

        api_key = self.config["api_key"]
        model = self.config["model"]
        custom_prompt = self.config["prompt"]

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}

        with open(audio_path, "rb") as f:
            audio_data = base64.b64encode(f.read()).decode("utf-8")

        prompt = (
            f"{custom_prompt}\n\n"
            "Please transcribe this audio. Return a JSON array of transcription segments with timestamps. "
            "Each segment must contain 'start' (float seconds), 'end' (float seconds), and 'text' (string transcription)."
        )

        payload = {
            "contents": [{
                "parts": [
                    {"inlineData": {"mimeType": "audio/mp3", "data": audio_data}},
                    {"text": prompt},
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
                            "text": {"type": "STRING", "description": "English transcript text"},
                        },
                        "required": ["start", "end", "text"],
                    },
                },
            },
        }

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=int(self.config.get("timeout", 90)),
        )
        if response.status_code != 200:
            raise Exception(f"Gemini API Error {response.status_code}: {response.text}")

        resp_data = response.json()
        candidate_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
        parsed_data = json.loads(candidate_text)
        return segments_from_timestamps(parsed_data)
