from abc import abstractmethod
from typing import List

from contracts import Segment
from http_utils import run_with_http_retry
from .base import STTProvider
from .common import validate_audio_file


class HTTPSTTProvider(STTProvider):
    """Base class for HTTP-based STT providers.

    Subclasses only need to implement _call_api() to perform the provider-specific
    API request and return parsed segments.
    """

    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config

    def transcribe(self, audio_path: str) -> List[Segment]:
        validate_audio_file(audio_path)

        def run_api_call():
            return self._call_api(audio_path)

        return run_with_http_retry(
            run_api_call,
            self.retry_config,
            self.__class__.__name__,
            "stt",
        )

    @abstractmethod
    def _call_api(self, audio_path: str) -> List[Segment]:
        """Perform the provider-specific API call and return transcription segments."""
        pass
