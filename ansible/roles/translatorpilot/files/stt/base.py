from abc import ABC, abstractmethod
from typing import List
from contracts import Segment

class STTProvider(ABC):
    """
    语音识别 (STT) 模块的抽象基类。
    所有 STT 提供商（如 Gemini, Whisper 等）都必须继承此类并实现其接口。
    """
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def transcribe(self, audio_path: str) -> List[Segment]:
        pass
