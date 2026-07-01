import os
import wave
import logging
import xml.etree.ElementTree as ET
from typing import List
from contracts import Segment
from retry import with_retry
from .base import TTSProvider

logger = logging.getLogger("tts")

class AzureSpeechTTS(TTSProvider):
    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config

    @property
    def name(self) -> str:
        return "azure_speech"

    def synthesize(self, segments: List[Segment], output_dir: str, on_segment_done=None) -> List[Segment]:
        if not segments:
            return []
            
        os.makedirs(output_dir, exist_ok=True)
        
        api_key = self.config.get("api_key") or os.environ.get("AZURE_SPEECH_KEY")
        region = self.config.get("region", "eastus") or os.environ.get("AZURE_SPEECH_REGION", "eastus")
        voice = self.config.get("voice", "zh-CN-XiaoxiaoNeural")

        if not api_key:
            logger.error("[TTS] Azure Subscription Key is missing. Cannot proceed.")
            raise RuntimeError("Fatal pipeline error")

        updated_segments = []
        for seg in segments:
            if not seg.target_text:
                logger.warning(f"[TTS] Segment {seg.segment_id} has no target text. Skipping synthesis.")
                updated_segments.append(seg)
                continue

            audio_filename = f"segment_{seg.segment_id}.wav"
            full_output_path = os.path.join(output_dir, audio_filename)

            def run_api_call():
                import requests
                import hashlib
                import shutil

                cache_dir = os.path.join(os.path.dirname(output_dir), "cache", "wav")
                os.makedirs(cache_dir, exist_ok=True)

                cache_key = hashlib.md5(f"{seg.target_text}_{voice}".encode("utf-8")).hexdigest()
                cache_filepath = os.path.join(cache_dir, f"{cache_key}.wav")

                if os.path.exists(cache_filepath):
                    logger.info(f"[TTS] Cache hit for segment {seg.segment_id}")
                    shutil.copy2(cache_filepath, full_output_path)
                    seg.audio_path = f"/output/{audio_filename}"
                    return
                
                escaped_text = self.escape_xml(seg.target_text)
                ssml = (
                    f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'>"
                    f"  <voice name='{voice}'>"
                    f"    {escaped_text}"
                    f"  </voice>"
                    f"</speak>"
                )

                endpoint = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
                headers = {
                    "Ocp-Apim-Subscription-Key": api_key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                    "User-Agent": "TranslatorPilot"
                }

                response = requests.post(endpoint, headers=headers, data=ssml.encode("utf-8"), timeout=30)
                if response.status_code != 200:
                    raise Exception(f"Azure Speech TTS API Error {response.status_code}: {response.text}")

                with open(full_output_path, "wb") as audio_file:
                    audio_file.write(response.content)
                
                shutil.copy2(full_output_path, cache_filepath)

                seg.audio_path = f"/output/{audio_filename}"

            try:
                with_retry(run_api_call, self.retry_config, f"AzureTTS-{seg.segment_id}")
            except Exception as e:
                logger.error(f"[TTS] Failed Azure synthesis for {seg.segment_id}: {e}.")
                raise RuntimeError("Fatal pipeline error")

            updated_segments.append(seg)
            if on_segment_done:
                on_segment_done(len(updated_segments), len(segments))

        return updated_segments

    def escape_xml(self, unsafe: str) -> str:
        return unsafe.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")



class GeminiTTS(TTSProvider):
    def __init__(self, retry_config: dict):
        self.retry_config = retry_config

    @property
    def name(self) -> str:
        return "gemini_tts"

    def synthesize(self, segments: List[Segment], output_dir: str, on_segment_done=None) -> List[Segment]:
        if not segments:
            return []
            
        os.makedirs(output_dir, exist_ok=True)
        api_key = os.environ.get("GEMINI_API_KEY")

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
                                    "voiceName": "Kore"
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
