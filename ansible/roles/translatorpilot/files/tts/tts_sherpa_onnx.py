import os
import wave
import array
import logging
from typing import List
from contracts import Segment
from .base import TTSProvider

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
        rule_fsts = ",".join([
            os.path.join(model_dir, "phone.fst"),
            os.path.join(model_dir, "date.fst"),
            os.path.join(model_dir, "number.fst"),
        ])

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

    def synthesize(self, segments: List[Segment], output_dir: str, on_segment_done=None) -> List[Segment]:
        if not segments:
            return []

        os.makedirs(output_dir, exist_ok=True)
        tts = self._load_engine()

        updated_segments = []
        for seg in segments:
            if not seg.target_text:
                logger.warning(f"[TTS] Segment {seg.segment_id} has no target text. Skipping synthesis.")
                updated_segments.append(seg)
                continue

            audio_filename = f"segment_{seg.segment_id}.wav"
            full_output_path = os.path.join(output_dir, audio_filename)

            try:
                audio = tts.generate(seg.target_text, sid=0, speed=1.0)
                self._write_wav(full_output_path, audio.samples, audio.sample_rate)
                seg.audio_path = f"/output/{audio_filename}"
            except Exception as e:
                logger.error(f"[TTS] Failed sherpa-onnx synthesis for {seg.segment_id}: {e}.")
                raise RuntimeError("Fatal pipeline error")

            updated_segments.append(seg)
            if on_segment_done:
                on_segment_done(len(updated_segments), len(segments))

        return updated_segments

    def _write_wav(self, path: str, samples, sample_rate: int):
        # sherpa-onnx returns float32 samples in [-1.0, 1.0]; convert to 16-bit PCM.
        int_samples = array.array(
            "h",
            [max(-32768, min(32767, int(s * 32767))) for s in samples],
        )
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(int_samples.tobytes())
