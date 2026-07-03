import os
from typing import List

from contracts import Segment


def validate_audio_file(audio_path: str) -> None:
    """Validate that audio file exists."""
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file to transcribe does not exist: {audio_path}")


def segments_from_timestamps(items: List[dict]) -> List[Segment]:
    """Build Segment list from dicts with start, end, and text keys."""
    return [
        Segment(
            start=float(item["start"]),
            end=float(item["end"]),
            source_text=item["text"].strip(),
        )
        for item in items
    ]


def segments_from_groq_response(result: dict) -> List[Segment]:
    """Parse Groq Whisper verbose_json response into segments."""
    segments_data = result.get("segments", [])
    if not segments_data:
        text = result.get("text", "No text transcribed")
        return [Segment(start=0.0, end=10.0, source_text=text)]
    return segments_from_timestamps(segments_data)
