import os
import logging
from typing import List, Callable, Optional
from contracts import Segment
from .base import TTSProvider
from cache import CacheManager
from .common import (
    generate_audio_filename,
    get_audio_path,
    should_skip_segment,
    write_wav_from_samples
)

logger = logging.getLogger("tts")


class SherpaOnnxTTS(TTSProvider):
    """
    Fully local, offline Chinese TTS using sherpa-onnx
    (Matcha-Icefall zh-baker acoustic model + Vocos vocoder).

    This is the same model family already verified on the Raspberry Pi 4B
    in the voice-assistant project (LVA). No network calls, no API key,
    no rate limits, no monthly quota.
    """

    def __init__(self, config: dict, retry_config: dict = None):
        self.config = config
        self._tts = None  # lazy-loaded on first synthesize() call
        self.volume_gain = float(self.config.get("volume_gain", 1.0))

    @property
    def name(self) -> str:
        return "sherpa_onnx"

    def _load_engine(self):
        if self._tts is not None:
            return self._tts

        import sherpa_onnx

        model_dir = self.config["model_dir"]
        vocoder_path = self.config["vocoder_path"]
        num_threads = int(self.config.get("num_threads", 2))

        acoustic_model = os.path.join(model_dir, "model-steps-3.onnx")
        lexicon = os.path.join(model_dir, "lexicon.txt")
        tokens = os.path.join(model_dir, "tokens.txt")

        # 从配置获取 fst 文件名，支持不同模型的文件名差异
        phone_fst_name = self.config.get("phone_fst", "phone.fst")
        date_fst_name = self.config.get("date_fst", "date.fst")
        number_fst_name = self.config.get("number_fst", "number.fst")

        phone_fst = os.path.join(model_dir, phone_fst_name)
        date_fst = os.path.join(model_dir, date_fst_name)
        number_fst = os.path.join(model_dir, number_fst_name)

        rule_fsts = ",".join([phone_fst, date_fst, number_fst])

        # 中英混合模型需要 data_dir（espeak-ng-data 目录）
        data_dir = os.path.join(model_dir, "espeak-ng-data")
        if not os.path.exists(data_dir):
            # 如果没有 espeak-ng-data，使用空字符串（纯中文模型）
            data_dir = ""

        for required_path in (acoustic_model, lexicon, tokens, vocoder_path):
            if not os.path.exists(required_path):
                raise FileNotFoundError(
                    f"[TTS] sherpa-onnx model file not found: {required_path}. "
                    f"Did the Ansible role finish downloading the model?"
                )

        tts_config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                    acoustic_model=acoustic_model,
                    vocoder=vocoder_path,
                    lexicon=lexicon,
                    tokens=tokens,
                    data_dir=data_dir,
                ),
                provider="cpu",
                debug=False,
                num_threads=num_threads,
            ),
            rule_fsts=rule_fsts,
        )

        if not tts_config.validate():
            raise RuntimeError(
                "[TTS] sherpa-onnx model configuration is invalid. "
                "Check model_dir / vocoder_path in settings.toml."
            )

        logger.info("[TTS] Loading sherpa-onnx Matcha model into memory (one-time cost)...")
        self._tts = sherpa_onnx.OfflineTts(tts_config)
        return self._tts

    def synthesize(self, segments: List[Segment], output_dir: str, 
                   on_segment_done: Optional[Callable[[int, int], None]] = None) -> List[Segment]:
        if not segments:
            return []

        os.makedirs(output_dir, exist_ok=True)
        tts = self._load_engine()

        cache = CacheManager("wav", output_dir)
        enable_cache = self.config.get("enable_cache", True)

        updated_segments = []
        for seg in segments:
            if should_skip_segment(seg):
                logger.warning(f"[TTS] Segment {seg.segment_id} has no target text. Skipping synthesis.")
                updated_segments.append(seg)
                continue

            full_output_path = get_audio_path(output_dir, seg.segment_id)

            # Cache key based on text and volume gain
            cache_key = cache.get_cache_key(seg.target_text, self.volume_gain)

            # Check cache
            if enable_cache and cache.exists(cache_key, ".wav"):
                logger.info(f"[TTS] Cache hit for segment {seg.segment_id}")
                cache.copy_from_cache(cache_key, full_output_path, ".wav")
                seg.audio_path = f"/output/{generate_audio_filename(seg.segment_id)}"
                updated_segments.append(seg)
                if on_segment_done:
                    on_segment_done(len(updated_segments), len(segments))
                continue

            try:
                audio = tts.generate(seg.target_text, sid=0, speed=1.0)
                write_wav_from_samples(audio.samples, full_output_path, audio.sample_rate)
                seg.audio_path = f"/output/{generate_audio_filename(seg.segment_id)}"
                # Save to cache
                if enable_cache:
                    cache.copy_file(cache_key, full_output_path, ".wav")
            except Exception as e:
                logger.error(f"[TTS] Failed sherpa-onnx synthesis for {seg.segment_id}: {e}.")
                raise RuntimeError("Fatal pipeline error")

            updated_segments.append(seg)
            if on_segment_done:
                on_segment_done(len(updated_segments), len(segments))

        return updated_segments
