import uuid
from typing import List, Optional
from dataclasses import dataclass, field

@dataclass
class Segment:
    """
    表示音频或文本分段的数据模型类。
    用于在语音识别 (STT)、翻译 (Translate) 和语音合成 (TTS) 模块之间传递核心数据。
    """
    # 唯一的段标识符，默认自动生成 UUID
    segment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # 音频片段在原音频中的起始时间 (单位：秒)
    start: float = 0.0
    # 音频片段在原音频中的结束时间 (单位：秒)
    end: float = 0.0
    # 语音识别 (STT) 模块提取出的源语言文本
    source_text: str = ""
    # 翻译模块生成的目标语言文本 (可选)
    target_text: Optional[str] = None
    # 语音合成 (TTS) 模块生成的音频文件保存路径 (可选)
    audio_path: Optional[str] = None
    # 提供给大语言模型翻译的上下文窗口历史句子列表，用于提升翻译连贯性 (可选)
    context_window: Optional[List[str]] = None
    # 标记当前数据段是否是通过降级或备用方案处理产生的
    is_fallback: bool = False
