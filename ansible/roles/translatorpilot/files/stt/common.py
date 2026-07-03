import os
from typing import List

from contracts import Segment


def validate_audio_file(audio_path: str) -> None:
    """
    验证待转录的音频文件是否存在。
    如果文件不存在，将抛出 FileNotFoundError 异常。
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file to transcribe does not exist: {audio_path}")


def segments_from_timestamps(items: List[dict]) -> List[Segment]:
    """
    将包含 start、end 和 text 键的字典列表转换为 Segment 数据结构列表。
    """
    return [
        Segment(
            start=float(item["start"]),
            end=float(item["end"]),
            source_text=item["text"].strip(),
        )
        for item in items
    ]


def segments_from_groq_response(result: dict) -> List[Segment]:
    """
    解析 Groq Whisper 返回的 verbose_json 格式响应，提取出包含时间戳的片段。
    如果响应中未包含片段信息，则将全部文本作为一个默认时长的片段返回。
    """
    segments_data = result.get("segments", [])
    if not segments_data:
        text = result.get("text", "No text transcribed")
        return [Segment(start=0.0, end=10.0, source_text=text)]
    return segments_from_timestamps(segments_data)
