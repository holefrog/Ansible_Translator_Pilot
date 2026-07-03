import os
import logging

from contracts import Segment
from cache import CacheManager
from .cached_segment_tts import CachedSegmentTTS
from .common import write_wav_from_samples

logger = logging.getLogger("tts")


class SherpaOnnxTTS(CachedSegmentTTS):
    """
    Fully local, offline Chinese TTS using sherpa-onnx
    (Matcha-Icefall zh-baker acoustic model + Vocos vocoder).
    """

    def __init__(self, config: dict, retry_config: dict = None):
        self.config = config
        self._tts = None
        self.volume_gain = float(self.config.get("volume_gain", 1.0))

    @property
    def name(self) -> str:
        return "sherpa_onnx"

    def build_cache_key(self, segment: Segment) -> str:
        return CacheManager.make_cache_key(segment.target_text, self.volume_gain)

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

        phone_fst_name = self.config.get("phone_fst", "phone.fst")
        date_fst_name = self.config.get("date_fst", "date.fst")
        number_fst_name = self.config.get("number_fst", "number.fst")

        phone_fst = os.path.join(model_dir, phone_fst_name)
        date_fst = os.path.join(model_dir, date_fst_name)
        number_fst = os.path.join(model_dir, number_fst_name)

        rule_fsts = ",".join([phone_fst, date_fst, number_fst])

        data_dir = os.path.join(model_dir, "espeak-ng-data")
        if not os.path.exists(data_dir):
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

    def _synthesize_segment(self, segment: Segment, output_path: str) -> None:
        tts = self._load_engine()
        audio = tts.generate(segment.target_text, sid=0, speed=1.0)
        write_wav_from_samples(audio.samples, output_path, audio.sample_rate)
