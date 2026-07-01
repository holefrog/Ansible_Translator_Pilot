from abc import ABC, abstractmethod
from typing import List, Optional, Callable
from contracts import Segment

class TTSProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def synthesize(self, segments: List[Segment], output_dir: str, on_segment_done: Optional[Callable[[int, int], None]] = None) -> List[Segment]:
        pass
