import os
import time
import wave
import logging
from typing import List
from contracts import Segment
from retry import with_retry
from .base import TTSProvider
from cache import CacheManager

logger = logging.getLogger("tts")

# NVIDIA Magpie TTS Multilingual HTTP endpoint
# Supports: en-US, zh-CN, es-ES, fr-FR, de-DE, ja-JP, hi-IN, it-IT, vi-VN
NVIDIA_MAGPIE_TTS_URL = (
    "https://877104f7-e885-42b9-8de8-f6e4c6303969"
    ".invocation.api.nvcf.nvidia.com/v1/audio/synthesize"
)

class NvidiaMagpieTTS(TTSProvider):
    """TTS provider using NVIDIA Magpie Multilingual model via Riva HTTP API.
    
    Supports Chinese (zh-CN) and many other languages.
    Voice format: Magpie-Multilingual.ZH-CN.<VoiceName>
    Common Chinese voices: Aria, Diego, HouZhen, Isabela, Long, Louise, Mia, Pascal, Ray, Siwei
    """

    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config
        self.last_request_time = 0
        # 从全局配置读取限速，默认 2 RPS (0.5秒间隔)
        rps = config.get("rate_limit", {}).get("tts_rps", 2)
        self.min_request_interval = 1.0 / rps if rps > 0 else 0.5

    @property
    def name(self) -> str:
        return "nvidia_magpie_tts"

    def synthesize(self, segments: List[Segment], output_dir: str, on_segment_done=None) -> List[Segment]:
        if not segments:
            return []

        os.makedirs(output_dir, exist_ok=True)
        api_key = self.config["api_key"]

        if not api_key:
            logger.error("[TTS] NVIDIA API Key is missing for TTS. Cannot proceed.")
            raise RuntimeError("Fatal pipeline error")

        language = self.config.get("language", "zh-CN")
        voice = self.config.get("voice", "Magpie-Multilingual.ZH-CN.Aria")
        sample_rate = int(self.config.get("sample_rate_hz", 44100))

        # 使用统一的缓存管理器
        cache = CacheManager("wav", output_dir)
        enable_cache = self.config.get("enable_cache", True)

        updated_segments = []
        for seg in segments:
            if not seg.target_text:
                updated_segments.append(seg)
                continue

            audio_filename = f"segment_{seg.segment_id}.wav"
            full_output_path = os.path.join(output_dir, audio_filename)

            # Cache key based on text, voice, language, and sample rate
            cache_key = cache.get_cache_key(seg.target_text, voice, language, sample_rate)

            # Check cache
            if enable_cache and cache.exists(cache_key, ".wav"):
                logger.info(f"[TTS] Cache hit for segment {seg.segment_id}")
                cache.copy_from_cache(cache_key, full_output_path, ".wav")
                seg.audio_path = f"/output/{audio_filename}"
                updated_segments.append(seg)
                if on_segment_done:
                    on_segment_done(len(updated_segments), len(segments))
                continue

            def run_api_call(
                _seg=seg,
                _out=full_output_path,
                _lang=language,
                _voice=voice,
                _sr=sample_rate
            ):
                import requests

                # 限速：确保不超过 2 RPS
                current_time = time.time()
                time_since_last_request = current_time - self.last_request_time
                if time_since_last_request < self.min_request_interval:
                    sleep_time = self.min_request_interval - time_since_last_request
                    logger.debug(f"[TTS] Rate limiting: sleeping {sleep_time:.2f}s before request")
                    time.sleep(sleep_time)
                self.last_request_time = time.time()

                headers = {
                    "Authorization": f"Bearer {api_key}"
                }

                # NVIDIA Riva HTTP TTS uses multipart/form-data
                data = {
                    "text": _seg.target_text,
                    "language": _lang,
                    "voice": _voice,
                    "encoding": "LINEAR_PCM",
                    "sample_rate_hz": str(_sr)
                }

                response = requests.post(
                    NVIDIA_MAGPIE_TTS_URL,
                    headers=headers,
                    data=data,
                    timeout=int(self.config.get("timeout", 60))
                )

                if response.status_code != 200:
                    raise Exception(
                        f"NVIDIA Magpie TTS API Error {response.status_code}: {response.text}"
                    )

                # Response is raw PCM audio — wrap it in a WAV container
                pcm_data = response.content
                with wave.open(_out, "wb") as wav_file:
                    wav_file.setnchannels(1)       # mono
                    wav_file.setsampwidth(2)        # 16-bit
                    wav_file.setframerate(_sr)
                    wav_file.writeframes(pcm_data)

                _seg.audio_path = f"/output/{audio_filename}"

            try:
                with_retry(run_api_call, self.retry_config, f"NvidiaMagpieTTS-{seg.segment_id}")
                # Save to cache after successful synthesis
                if enable_cache:
                    cache.copy_file(cache_key, full_output_path, ".wav")
            except Exception as e:
                logger.error(f"[TTS] NVIDIA Magpie TTS synthesis failed for {seg.segment_id}: {e}")
                raise RuntimeError("Fatal pipeline error")

            updated_segments.append(seg)
            if on_segment_done:
                on_segment_done(len(updated_segments), len(segments))

        return updated_segments
