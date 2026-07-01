import os
import struct
import logging
from typing import List, dict
from core import Segment

logger = logging.getLogger("align_check")

def get_wav_duration(file_path: str) -> float:
    if not os.path.exists(file_path):
        logger.warning(f"[AlignCheck] WAV file not found: {file_path}")
        return 0.0

    try:
        with open(file_path, "rb") as f:
            header = f.read(44)
            if len(header) < 44:
                return 0.0

            is_riff = header[0:4] == b"RIFF"
            is_wave = header[8:12] == b"WAVE"

            if not is_riff or not is_wave:
                # Estimate based on file size and common Azure format (24kHz 16-bit mono = 48000 bytes/sec)
                file_size = os.path.getsize(file_path)
                return file_size / 48000.0

            # Scan subchunks to find fmt and data
            f.seek(12)
            sample_rate = 24000
            channels = 1
            bits_per_sample = 16
            data_size = 0
            
            # Simple chunk parsing
            file_size = os.path.getsize(file_path)
            pos = 12
            while pos < file_size - 8:
                f.seek(pos)
                chunk_id = f.read(4)
                chunk_size_bytes = f.read(4)
                if len(chunk_size_bytes) < 4:
                    break
                chunk_size = struct.unpack("<I", chunk_size_bytes)[0]
                
                if chunk_id == b"fmt ":
                    f.seek(pos + 8 + 2)
                    channels = struct.unpack("<H", f.read(2))[0]
                    sample_rate = struct.unpack("<I", f.read(4))[0]
                    f.seek(pos + 8 + 14)
                    bits_per_sample = struct.unpack("<H", f.read(2))[0]
                elif chunk_id == b"data":
                    data_size = chunk_size
                    break
                    
                pos += 8 + chunk_size

            if data_size == 0:
                data_size = file_size - 44

            bytes_per_second = sample_rate * channels * (bits_per_sample / 8)
            if bytes_per_second == 0:
                return 0.0
                
            return data_size / bytes_per_second
            
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
