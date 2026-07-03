import os
import json
import logging
from typing import List
from contracts import Segment
from retry import with_retry
from .base import STTProvider

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

        if not api_key:
            logger.warning("[STT] Groq API key is missing. Using pre-loaded mock demonstration segments.")
            return self.get_mock_segments()

        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file to transcribe does not exist: {audio_path}")

        def run_api_call():
            import requests
            url = "https://api.groq.com/openai/v1/audio/transcriptions"
            headers = {
                "Authorization": f"Bearer {api_key}"
            }
            files = {
                "file": ("audio.mp3", open(audio_path, "rb"), "audio/mpeg")
            }
            prompt_path = self.config.get("prompt_path")
            if not prompt_path:
                logger.error("[STT] Prompt path is missing from config.")
                raise RuntimeError("Fatal pipeline error")
                
            if not os.path.exists(prompt_path):
                logger.error(f"[STT] Prompt file not found: {prompt_path}")
                raise RuntimeError("Fatal pipeline error")
                
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompt_text = f.read()

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
            logger.error("[STT] 'requests' library not found. Run 'pip install requests'. Falling back to mock data.")
            return self.get_mock_segments()

    def get_mock_segments(self) -> List[Segment]:
        return [
            Segment(
                start=0.0,
                end=5.5,
                source_text="Welcome to the future of translation technology with Translator Pilot.",
                is_fallback=True
            ),
            Segment(
                start=6.2,
                end=12.8,
                source_text="This pipeline runs Whisper for transcription, Gemini for translation, and Azure for speech synthesis.",
                is_fallback=True
            ),
            Segment(
                start=13.5,
                end=19.4,
                source_text="It is designed to be extremely fast, robust, and running entirely offline or hybrid.",
                is_fallback=True
            ),
            Segment(
                start=20.0,
                end=26.5,
                source_text="Let's perform a length check to ensure the Chinese dubbed audio aligns nicely with the original English timing.",
                is_fallback=True
            )
        ]

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
            logger.warning("[STT] Gemini API key is missing. Using pre-loaded mock demonstration segments.")
            return GroqWhisperSTT({}, {}).get_mock_segments()

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
                
            prompt_path = self.config.get("prompt_path")
            if not prompt_path:
                logger.error("[STT] Prompt path is missing from config.")
                raise RuntimeError("Fatal pipeline error")
                
            if not os.path.exists(prompt_path):
                logger.error(f"[STT] Prompt file not found: {prompt_path}")
                raise RuntimeError("Fatal pipeline error")
                
            with open(prompt_path, "r", encoding="utf-8") as f:
                custom_prompt = f.read()

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
            logger.error("[STT] 'requests' library not found. Falling back to mock data.")
            return GroqWhisperSTT({}, {}).get_mock_segments()
