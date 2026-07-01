import os
import logging
from typing import List
from contracts import Segment
from retry import with_retry
from .base import TTSProvider

logger = logging.getLogger("tts")

class GeminiTTS(TTSProvider):
    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config

    @property
    def name(self) -> str:
        return "gemini_tts"

    def synthesize(self, segments: List[Segment], output_dir: str, on_segment_done=None) -> List[Segment]:
        if not segments:
            return []
            
        os.makedirs(output_dir, exist_ok=True)
        api_key = self.config["api_key"]

        if not api_key:
            logger.error("[TTS] Gemini API Key is missing for TTS. Cannot proceed.")
            raise RuntimeError("Fatal pipeline error")

        updated_segments = []
        for seg in segments:
            if not seg.target_text:
                updated_segments.append(seg)
                continue

            audio_filename = f"segment_{seg.segment_id}.wav"
            full_output_path = os.path.join(output_dir, audio_filename)

            def run_api_call():
                import requests
                import base64
                
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-tts-preview:generateContent?key={api_key}"
                headers = {"Content-Type": "application/json"}
                
                payload = {
                    "contents": [{
                        "parts": [{"text": f"Read this in natural Chinese: {seg.target_text}"}]
                    }],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {
                                    "voiceName": self.config["voice"]
                                }
                            }
                        }
                    }
                }

                response = requests.post(url, headers=headers, json=payload, timeout=30)
                if response.status_code != 200:
                    raise Exception(f"Gemini TTS API Error {response.status_code}: {response.text}")

                resp_data = response.json()
                base64_audio = resp_data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                
                with open(full_output_path, "wb") as f:
                    f.write(base64.b64decode(base64_audio))

                seg.audio_path = f"/output/{audio_filename}"

            try:
                with_retry(run_api_call, self.retry_config, f"GeminiTTS-{seg.segment_id}")
            except Exception as e:
                logger.error(f"[TTS] Gemini TTS synthesis failed for {seg.segment_id}: {e}")
                raise RuntimeError("Fatal pipeline error")

            updated_segments.append(seg)
            if on_segment_done:
                on_segment_done(len(updated_segments), len(segments))

        return updated_segments
