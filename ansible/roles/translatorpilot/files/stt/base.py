from abc import ABC, abstractmethod
from typing import List
from core import Segment

class STTProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def transcribe(self, audio_path: str) -> List[Segment]:
        pass
