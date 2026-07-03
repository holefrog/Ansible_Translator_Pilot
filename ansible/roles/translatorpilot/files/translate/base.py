from abc import ABC, abstractmethod
from typing import List
from contracts import Segment

class TranslateProvider(ABC):
    """
    大语言模型翻译模块的抽象基类。
    所有翻译引擎提供商都必须实现其接口以完成字幕翻译功能。
    """
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def translate(self, segments: List[Segment]) -> List[Segment]:
        pass
