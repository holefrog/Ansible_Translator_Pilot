import os
import logging
from typing import List
from contracts import Segment
from retry import with_retry
from .base import TTSProvider
from cache import CacheManager

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

            # 使用统一的缓存管理器
            cache = CacheManager("wav", output_dir)
            voice = self.config["voice"]
            cache_key = cache.get_cache_key(seg.target_text, voice)

            # Check cache
            if cache.exists(cache_key, ".wav"):
                logger.info(f"[TTS] Cache hit for segment {seg.segment_id}")
                cache.copy_from_cache(cache_key, full_output_path, ".wav")
                seg.audio_path = f"/output/{audio_filename}"
                updated_segments.append(seg)
                if on_segment_done:
                    on_segment_done(len(updated_segments), len(segments))
                continue

            def run_api_call():
                import requests
                import base64
                
                model = self.config["model"]
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
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

                import time
                
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

                import wave
                import io

                resp_data = response.json()
                base64_audio = resp_data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                pcm_data = base64.b64decode(base64_audio)
                
                # Gemini TTS returns raw PCM (24kHz, 16-bit, mono). We need to add a WAV header.
                wav_io = io.BytesIO()
                with wave.open(wav_io, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(24000)
                    wav_file.writeframes(pcm_data)
                
                with open(full_output_path, "wb") as f:
                    f.write(wav_io.getvalue())

                # Save to cache
                cache.copy_file(cache_key, full_output_path, ".wav")

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
