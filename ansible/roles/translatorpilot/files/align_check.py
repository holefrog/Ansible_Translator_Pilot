import os
import wave
import logging
from typing import List, dict
from contracts import Segment

logger = logging.getLogger("align_check")

def get_wav_duration(file_path: str) -> float:
    if not os.path.exists(file_path):
        logger.warning(f"[AlignCheck] WAV file not found: {file_path}")
        return 0.0

    try:
        with wave.open(file_path, "rb") as f:
            return f.getnframes() / float(f.getframerate())
    except Exception as e:
        logger.error(f"[AlignCheck] Failed to parse WAV duration: {e}")
        # Default safety fallback calculation
        file_size = os.path.getsize(file_path)
        return file_size / 48000.0

def check_alignment(segments: List[Segment], server_output_dir: str, threshold_ratio: float = 1.3) -> List[dict]:
    results = []

    for seg in segments:
        original_duration = seg.end - seg.start
        synthesized_duration = 0.0

        if seg.audio_path:
            # Locate file on disk
            filename = os.path.basename(seg.audio_path)
            absolute_path = os.path.join(server_output_dir, filename)
            synthesized_duration = get_wav_duration(absolute_path)

        ratio = synthesized_duration / original_duration if original_duration > 0 else 1.0
        warning = ratio > threshold_ratio
        
        message = f"Timing aligned perfectly ({ratio:.2f}x duration ratio)."
        if warning:
            message = (
                f"WARNING: Chinese dubbed audio is too long! ({synthesized_duration:.2f}s "
                f"vs English segment {original_duration:.2f}s). Segment ratio of {ratio:.2f}x "
                f"exceeds threshold ({threshold_ratio}x). The audio will overflow and sound rushed or clip."
            )
        elif synthesized_duration == 0:
            message = "No synthesized audio generated yet."

        results.append({
            "segment_id": seg.segment_id,
            "source_text": seg.source_text,
            "target_text": seg.target_text or "",
            "original_duration": original_duration,
            "synthesized_duration": synthesized_duration,
            "ratio": ratio,
            "warning": warning,
            "message": message
        })

    return results
