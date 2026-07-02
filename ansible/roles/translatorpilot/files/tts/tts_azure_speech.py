import os
import wave
import logging
import xml.etree.ElementTree as ET
from typing import List
from contracts import Segment
from retry import with_retry
from .base import TTSProvider
from cache import CacheManager

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
        
        api_key = self.config["api_key"]
        region = self.config["region"]
        voice = self.config["voice"]

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
                # 使用统一的缓存管理器
                cache = CacheManager("wav", output_dir)
                enable_cache = self.config.get("enable_cache", True)
                cache_key = cache.get_cache_key(seg.target_text, voice)

                if enable_cache and cache.exists(cache_key, ".wav"):
                    logger.info(f"[TTS] Cache hit for segment {seg.segment_id}")
                    cache.copy_from_cache(cache_key, full_output_path, ".wav")
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

                response = requests.post(endpoint, headers=headers, data=ssml.encode("utf-8"), timeout=int(self.config.get("timeout", 30)))
                if response.status_code != 200:
                    raise Exception(f"Azure Speech TTS API Error {response.status_code}: {response.text}")

                with open(full_output_path, "wb") as audio_file:
                    audio_file.write(response.content)
                
                if enable_cache:
                    cache.copy_file(cache_key, full_output_path, ".wav")

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


