import logging
from contracts import Segment
from retry import with_retry
from .cached_segment_tts import CachedSegmentTTS
from .common import RateLimiter

logger = logging.getLogger("tts")


class HTTPRateLimitedTTS(CachedSegmentTTS):
    """
    带有限流和按片段重试机制的 HTTP TTS 基类。
    
    子类需要实现 `build_cache_key()` 和 `synthesize_audio()` 方法。
    """

    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config
        rps = config.get("rate_limit", {}).get("tts_rps", 2)
        self.rate_limiter = RateLimiter(rps)

    def _synthesize_segment(self, segment: Segment, output_path: str) -> None:
        def run_api_call():
            self.rate_limiter.wait_if_needed()
            self.synthesize_audio(segment, output_path)

        with_retry(
            run_api_call,
            self.retry_config,
            f"{self.__class__.__name__}-{segment.segment_id}",
        )

    def synthesize_audio(self, segment: Segment, output_path: str) -> None:
        raise NotImplementedError("Subclass must implement synthesize_audio")
