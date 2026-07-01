import os
import math
import struct
import logging
import xml.etree.ElementTree as ET
from typing import List
from core import Segment, with_retry
from .base import TTSProvider

logger = logging.getLogger("tts")

class AzureSpeechTTS(TTSProvider):
    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config

    @property
    def name(self) -> str:
        return "azure_speech"

    def synthesize(self, segments: List[Segment], output_dir: str) -> List[Segment]:
        if not segments:
            return []
            
        os.makedirs(output_dir, exist_ok=True)
        
        api_key = self.config.get("api_key") or os.environ.get("AZURE_SPEECH_KEY")
        region = self.config.get("region", "eastus") or os.environ.get("AZURE_SPEECH_REGION", "eastus")
        voice = self.config.get("voice", "zh-CN-XiaoxiaoNeural")

        if not api_key:
            logger.warning("[TTS] Azure Subscription Key is missing. Generating pure local synthetic waves.")
            return self.synthesize_with_synthetic_wav(segments, output_dir)

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

                seg.audio_path = f"/output/{audio_filename}"

            try:
                with_retry(run_api_call, self.retry_config, f"AzureTTS-{seg.segment_id}")
            except Exception as e:
                logger.error(f"[TTS] Failed Azure synthesis for {seg.segment_id}: {e}. Falling back to synthetic wave.")
                self.generate_beep_wav(full_output_path, max(1.5, min(seg.end - seg.start, len(seg.target_text or "") * 0.25)))
                seg.audio_path = f"/output/{audio_filename}"

            updated_segments.append(seg)

        return updated_segments

    def escape_xml(self, unsafe: str) -> str:
        return unsafe.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")

    def synthesize_with_synthetic_wav(self, segments: List[Segment], output_dir: str) -> List[Segment]:
        updated = []
        for seg in segments:
            audio_filename = f"segment_{seg.segment_id}.wav"
            full_output_path = os.path.join(output_dir, audio_filename)
            
            text_len = len(seg.target_text or "")
            target_duration = max(1.5, min(seg.end - seg.start, text_len * 0.25))
            
            self.generate_beep_wav(full_output_path, target_duration)
            seg.audio_path = f"/output/{audio_filename}"
            updated.append(seg)
        return updated

    def generate_beep_wav(self, file_path: str, duration: float):
        sample_rate = 8000
        num_samples = int(sample_rate * duration)
        frequency = 440.0
        
        # WAV container generation in pure Python using 'struct' package
        with open(file_path, "wb") as f:
            # 1. RIFF Header
            f.write(b"RIFF")
            f.write(struct.pack("<I", 36 + num_samples * 2))
            f.write(b"WAVE")
            
            # 2. fmt Subchunk
            f.write(b"fmt ")
            f.write(struct.pack("<I", 16)) # Subchunk1Size
            f.write(struct.pack("<H", 1))  # AudioFormat (PCM = 1)
            f.write(struct.pack("<H", 1))  # NumChannels (Mono)
            f.write(struct.pack("<I", sample_rate)) # SampleRate
            f.write(struct.pack("<I", sample_rate * 2)) # ByteRate
            f.write(struct.pack("<H", 2))  # BlockAlign
            f.write(struct.pack("<H", 16)) # BitsPerSample
            
            # 3. data Subchunk
            f.write(b"data")
            f.write(struct.pack("<I", num_samples * 2))
            
            # Synthesize Sine Wave Tone
            for i in range(num_samples):
                t = float(i) / sample_rate
                sample_value = math.sin(2.0 * math.pi * frequency * t)
                int_sample = int(sample_value * 32767)
                f.write(struct.pack("<h", int_sample))

class GeminiTTS(TTSProvider):
    def __init__(self, retry_config: dict):
        self.retry_config = retry_config

    @property
    def name(self) -> str:
        return "gemini_tts"

    def synthesize(self, segments: List[Segment], output_dir: str) -> List[Segment]:
        if not segments:
            return []
            
        os.makedirs(output_dir, exist_ok=True)
        api_key = os.environ.get("GEMINI_API_KEY")

        if not api_key:
            logger.warning("[TTS] Gemini API Key is missing for TTS. Falling back to synthetic generator.")
            return AzureSpeechTTS({}, self.retry_config).synthesize(segments, output_dir)

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
                AzureSpeechTTS({}, self.retry_config).generate_beep_wav(full_output_path, max(1.5, min(seg.end - seg.start, len(seg.target_text) * 0.25)))
                seg.audio_path = f"/output/{audio_filename}"

            updated_segments.append(seg)

        return updated_segments
