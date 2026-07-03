import os
import logging

logger = logging.getLogger("stt")


def validate_audio_file(audio_path: str) -> None:
    """Validate that audio file exists.
    
    Args:
        audio_path: Path to audio file
        
    Raises:
        FileNotFoundError: If audio file does not exist
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file to transcribe does not exist: {audio_path}")
