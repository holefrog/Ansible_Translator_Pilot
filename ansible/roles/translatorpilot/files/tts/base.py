from abc import ABC, abstractmethod
from typing import List
from contracts import Segment

class TTSProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def synthesize(self, segments: List[Segment], output_dir: str) -> List[Segment]:
        pass
