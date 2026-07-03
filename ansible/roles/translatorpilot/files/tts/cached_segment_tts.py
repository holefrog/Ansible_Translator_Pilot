import os
import logging
from abc import abstractmethod
from typing import List, Callable, Optional

from contracts import Segment
from cache import CacheManager
from .base import TTSProvider
from .common import generate_audio_filename, get_audio_path, should_skip_segment

logger = logging.getLogger("tts")


class CachedSegmentTTS(TTSProvider):
    """Base class for per-segment TTS with caching and empty-text skipping.

    Subclasses implement _synthesize_segment() to produce audio for one segment.
    """

    def synthesize(
        self,
        segments: List[Segment],
        output_dir: str,
        on_segment_done: Optional[Callable[[int, int], None]] = None,
    ) -> List[Segment]:
        if not segments:
            return []

        os.makedirs(output_dir, exist_ok=True)
        cache = CacheManager("wav", output_dir)
        enable_cache = self.config.get("enable_cache", True)

        updated_segments = []
        for seg in segments:
            if should_skip_segment(seg):
                logger.warning(
                    f"[TTS] Segment {seg.segment_id} has no target text. Skipping synthesis."
                )
                updated_segments.append(seg)
                continue

            full_output_path = get_audio_path(output_dir, seg.segment_id)
            cache_key = self.build_cache_key(seg)

            if enable_cache and cache.exists(cache_key, ".wav"):
                logger.info(f"[TTS] Cache hit for segment {seg.segment_id}")
                cache.copy_from_cache(cache_key, full_output_path, ".wav")
                seg.audio_path = f"/output/{generate_audio_filename(seg.segment_id)}"
                updated_segments.append(seg)
                if on_segment_done:
                    on_segment_done(len(updated_segments), len(segments))
                continue

            try:
                self._synthesize_segment(seg, full_output_path)
                seg.audio_path = f"/output/{generate_audio_filename(seg.segment_id)}"
                if enable_cache:
                    cache.copy_file(cache_key, full_output_path, ".wav")
            except Exception as e:
                logger.error(f"[TTS] Failed {self.name} synthesis for {seg.segment_id}: {e}.")
                raise RuntimeError("Fatal pipeline error") from e

            updated_segments.append(seg)
            if on_segment_done:
                on_segment_done(len(updated_segments), len(segments))

        return updated_segments

    def build_cache_key(self, segment: Segment) -> str:
        return CacheManager.make_cache_key(segment.target_text)

    @abstractmethod
    def _synthesize_segment(self, segment: Segment, output_path: str) -> None:
        """Synthesize audio for a single segment and write to output_path."""
        pass
