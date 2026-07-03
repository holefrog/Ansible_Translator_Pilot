import logging
import xml.etree.ElementTree as ET
from contracts import Segment
from .http_rate_limited import HTTPRateLimitedTTS
from cache import CacheManager

logger = logging.getLogger("tts")

class AzureSpeechTTS(HTTPRateLimitedTTS):
    def __init__(self, config: dict, retry_config: dict):
        super().__init__(config, retry_config)

    @property
    def name(self) -> str:
        return "azure_speech"

    def build_cache_key(self, segment: Segment) -> str:
        cache = CacheManager("wav", "")
        voice = self.config["voice"]
        return cache.get_cache_key(segment.target_text, voice)

    def synthesize_audio(self, segment: Segment, output_path: str) -> None:
        import requests
        
        api_key = self.config["api_key"]
        region = self.config["region"]
        voice = self.config["voice"]
        
        escaped_text = self.escape_xml(segment.target_text)
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

        with open(output_path, "wb") as audio_file:
            audio_file.write(response.content)

    def escape_xml(self, unsafe: str) -> str:
        return unsafe.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


