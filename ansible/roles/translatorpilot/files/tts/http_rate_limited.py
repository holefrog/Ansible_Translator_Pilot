import os
import logging
from typing import List, Callable, Optional
from contracts import Segment
from retry import with_retry
from .base import TTSProvider
from cache import CacheManager
from .common import (
    RateLimiter,
    generate_audio_filename,
    get_audio_path,
    should_skip_segment
)

logger = logging.getLogger("tts")


class HTTPRateLimitedTTS(TTSProvider):
    """Base class for HTTP-based TTS providers with rate limiting and caching.
    
    This class implements the common synthesis workflow for HTTP-based TTS providers:
    - Rate limiting to avoid API rate limits
    - Caching of synthesized audio
    - Common segment processing loop
    - Empty text skipping
    
    Subclasses only need to override:
    - build_cache_key(): Generate cache key for segment
    - synthesize_audio(): Perform the actual API call to synthesize audio
    """
    
    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config
        # Initialize rate limiter
        rps = config.get("rate_limit", {}).get("tts_rps", 2)
        self.rate_limiter = RateLimiter(rps)
    
    def synthesize(self, segments: List[Segment], output_dir: str, 
                   on_segment_done: Optional[Callable[[int, int], None]] = None) -> List[Segment]:
        if not segments:
            return []
        
        os.makedirs(output_dir, exist_ok=True)
        
        cache = CacheManager("wav", output_dir)
        enable_cache = self.config.get("enable_cache", True)
        
        updated_segments = []
        for seg in segments:
            if should_skip_segment(seg):
                logger.warning(f"[TTS] Segment {seg.segment_id} has no target text. Skipping synthesis.")
                updated_segments.append(seg)
                continue
            
            full_output_path = get_audio_path(output_dir, seg.segment_id)
            cache_key = self.build_cache_key(seg)
            
            # Check cache
            if enable_cache and cache.exists(cache_key, ".wav"):
                logger.info(f"[TTS] Cache hit for segment {seg.segment_id}")
                cache.copy_from_cache(cache_key, full_output_path, ".wav")
                seg.audio_path = f"/output/{generate_audio_filename(seg.segment_id)}"
                updated_segments.append(seg)
                if on_segment_done:
                    on_segment_done(len(updated_segments), len(segments))
                continue
            
            # Synthesize audio
            def run_api_call():
                self.rate_limiter.wait_if_needed()
                self.synthesize_audio(seg, full_output_path)
                seg.audio_path = f"/output/{generate_audio_filename(seg.segment_id)}"
            
            try:
                with_retry(run_api_call, self.retry_config, f"{self.__class__.__name__}-{seg.segment_id}")
                # Save to cache after successful synthesis
                if enable_cache:
                    cache.copy_file(cache_key, full_output_path, ".wav")
            except Exception as e:
                logger.error(f"[TTS] Failed {self.name} synthesis for {seg.segment_id}: {e}.")
                raise RuntimeError("Fatal pipeline error")
            
            updated_segments.append(seg)
            if on_segment_done:
                on_segment_done(len(updated_segments), len(segments))
        
        return updated_segments
    
    def build_cache_key(self, segment: Segment) -> str:
        """Generate cache key for a segment.
        
        Args:
            segment: Segment to generate cache key for
            
        Returns:
            Cache key string
        """
        cache = CacheManager("wav", "")
        # Default implementation uses target_text only
        # Subclasses should override to include provider-specific parameters
        return cache.get_cache_key(segment.target_text)
    
    def synthesize_audio(self, segment: Segment, output_path: str) -> None:
        """Synthesize audio for a single segment.
        
        This method must be overridden by subclasses to perform the actual
        API call and save the audio to output_path.
        
        Args:
            segment: Segment to synthesize
            output_path: Path to save the audio file
        """
        raise NotImplementedError("Subclass must implement synthesize_audio")
