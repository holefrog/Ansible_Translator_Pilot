from abc import ABC, abstractmethod
from typing import List
from core.contracts import Segment

class TranslateProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def translate(self, segments: List[Segment]) -> List[Segment]:
        pass
