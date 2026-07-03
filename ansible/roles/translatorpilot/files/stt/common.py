import os
import logging

logger = logging.getLogger("stt")


def validate_api_key(api_key: str, provider_name: str) -> None:
    """Validate that API key is present.
    
    Args:
        api_key: API key to validate
        provider_name: Name of the provider for error message
        
    Raises:
        RuntimeError: If API key is missing
    """
    if not api_key:
        logger.error(f"[STT] {provider_name} API key is missing.")
        raise RuntimeError(f"Fatal pipeline error: {provider_name} API key is missing")


def validate_audio_file(audio_path: str) -> None:
    """Validate that audio file exists.
    
    Args:
        audio_path: Path to audio file
        
    Raises:
        FileNotFoundError: If audio file does not exist
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file to transcribe does not exist: {audio_path}")
