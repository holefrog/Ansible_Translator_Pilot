import os
import time
import wave
import io
import logging
from typing import Optional

logger = logging.getLogger("tts")


class RateLimiter:
    """Rate limiter for API requests to avoid hitting rate limits."""
    
    def __init__(self, rps: float = 2.0):
        """
        Initialize rate limiter.
        
        Args:
            rps: Requests per second limit
        """
        self.last_request_time = 0
        self.min_request_interval = 1.0 / rps if rps > 0 else 0.5
    
    def wait_if_needed(self) -> None:
        """Wait if necessary to respect rate limit."""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last_request
            logger.debug(f"[TTS] Rate limiting: sleeping {sleep_time:.2f}s before request")
            time.sleep(sleep_time)
        self.last_request_time = time.time()


def generate_audio_filename(segment_id: str) -> str:
    """Generate audio filename for a segment.
    
    Args:
        segment_id: Segment identifier
        
    Returns:
        Audio filename (e.g., "segment_1.wav")
    """
    return f"segment_{segment_id}.wav"


def get_audio_path(output_dir: str, segment_id: str) -> str:
    """Get full audio file path for a segment.
    
    Args:
        output_dir: Output directory
        segment_id: Segment identifier
        
    Returns:
        Full path to audio file
    """
    audio_filename = generate_audio_filename(segment_id)
    return os.path.join(output_dir, audio_filename)


def wrap_pcm_as_wav(pcm_data: bytes, output_path: str, sample_rate: int = 24000) -> None:
    """Wrap raw PCM data in WAV container.
    
    Args:
        pcm_data: Raw PCM audio data
        output_path: Output WAV file path
        sample_rate: Sample rate in Hz (default 24000 for Gemini)
    """
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    
    with open(output_path, "wb") as f:
        f.write(wav_io.getvalue())


def write_wav_from_samples(samples, output_path: str, sample_rate: int) -> None:
    """Write samples directly to WAV file (for sherpa-onnx).
    
    Args:
        samples: Audio samples (float32 in [-1.0, 1.0])
        output_path: Output WAV file path
        sample_rate: Sample rate in Hz
    """
    import array
    
    int_samples = array.array(
        "h",
        [max(-32768, min(32767, int(s * 32767))) for s in samples],
    )
    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int_samples.tobytes())


def should_skip_segment(segment) -> bool:
    """Check if segment should be skipped (no target text).
    
    Args:
        segment: Segment object
        
    Returns:
        True if segment should be skipped
    """
    return not segment.target_text
