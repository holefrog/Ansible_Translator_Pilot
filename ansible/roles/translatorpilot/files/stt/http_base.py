from abc import abstractmethod
from typing import List

from contracts import Segment
from http_utils import run_with_http_retry
from .base import STTProvider
from .common import validate_audio_file


class HTTPSTTProvider(STTProvider):
    """
    基于 HTTP 接口的 STT 提供商基类。
    
    子类只需要实现 `_call_api()` 方法以执行特定的 API 请求并返回解析后的片段。
    该基类会自动处理音频文件验证和 HTTP 网络请求重试逻辑。
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
        """
        执行特定提供商的 API 请求，并返回解析后的语音片段列表。
        必须由具体的提供商子类实现。
        """
        pass
