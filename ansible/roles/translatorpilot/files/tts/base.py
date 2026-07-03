from abc import ABC, abstractmethod
from typing import List, Optional, Callable
from contracts import Segment

class TTSProvider(ABC):
    """
    语音合成 (TTS) 模块的抽象基类。
    所有 TTS 提供商必须实现名称和语音合成接口。
    """
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def synthesize(self, segments: List[Segment], output_dir: str, on_segment_done: Optional[Callable[[int, int], None]] = None) -> List[Segment]:
        pass
