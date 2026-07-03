import os
import wave
import logging
from typing import List
from contracts import Segment

logger = logging.getLogger("align_check")

def get_wav_duration(file_path: str) -> float:
    """
    读取并获取 WAV 音频文件的时长（秒）。
    如果文件不存在或解析失败，将回退至安全的字节大小估算。

    参数:
        file_path (str): WAV 文件的绝对路径。

    返回:
        float: 音频时长（单位：秒）。
    """
    if not os.path.exists(file_path):
        logger.warning(f"[AlignCheck] 找不到 WAV 文件: {file_path}")
        return 0.0

    try:
        with wave.open(file_path, "rb") as f:
            # 时长 = 总帧数 / 采样率
            return f.getnframes() / float(f.getframerate())
    except Exception as e:
        logger.error(f"[AlignCheck] 解析 WAV 时长失败: {e}")
        # 默认的安全备用计算方案 (基于 16位单声道 48kHz 的粗略估算)
        file_size = os.path.getsize(file_path)
        return file_size / 48000.0

def check_alignment(segments: List[Segment], server_output_dir: str, threshold_ratio: float = 1.3) -> List[dict]:
    """
    检查生成的语音片段是否与原始片段的时间戳对齐。
    通过比对生成的中文合成语音时长和英文原始片段时长，
    如果超出设定的比例阈值，则生成溢出警告。

    参数:
        segments (List[Segment]): 待检查的段落列表。
        server_output_dir (str): 合成音频文件的存放根目录。
        threshold_ratio (float): 允许的时长增长比例上限，默认 1.3 倍。

    返回:
        List[dict]: 每个段落的对齐检查结果列表，包含时长比例和警告信息。
    """
    results = []

    for seg in segments:
        original_duration = seg.end - seg.start
        synthesized_duration = 0.0

        if seg.audio_path:
            # 在磁盘上定位合成的音频文件
            filename = os.path.basename(seg.audio_path)
            absolute_path = os.path.join(server_output_dir, filename)
            synthesized_duration = get_wav_duration(absolute_path)

        # 计算合成音频与原音频的时长比例
        ratio = synthesized_duration / original_duration if original_duration > 0 else 1.0
        warning = ratio > threshold_ratio
        
        message = f"时长完美对齐 (时长比例为 {ratio:.2f}x)。"
        if warning:
            message = (
                f"警告：中文配音音频过长！(合成音频 {synthesized_duration:.2f} 秒 "
                f"vs 英文原音频片段 {original_duration:.2f} 秒)。时长比例达到了 {ratio:.2f}x，"
                f"超过了设定的阈值 ({threshold_ratio}x)。这将导致配音溢出、语速听起来过于急促或被截断。"
            )
        elif synthesized_duration == 0:
            message = "尚未生成任何合成语音音频。"

        results.append({
            "segment_id": seg.segment_id,
            "source_text": seg.source_text,
            "target_text": seg.target_text or "",
            "original_duration": original_duration,
            "synthesized_duration": synthesized_duration,
            "ratio": ratio,
            "warning": warning,
            "message": message
        })

    return results
