import os
import sys
import json
import logging
from typing import Callable, Optional
from contracts import Segment
from stt import GroqWhisperSTT, GeminiSTT
from translate import TranslateProvider, GeminiTranslate, GroqTranslate
from tts import AzureSpeechTTS, GeminiTTS
from align_check import check_alignment

# Set up logging configuration
logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("pipeline")

class TranslatorPilotPipeline:
    def __init__(self, settings: dict, output_dir: str):
        self.settings = settings
        self.output_dir = output_dir

    def run(self, audio_path: str, on_progress: Optional[Callable[[str, int], None]] = None) -> dict:
        state_file = os.path.join(self.output_dir, "pipeline_state.json")
        os.makedirs(self.output_dir, exist_ok=True)
        current_segments = []
        
        def dump_state(status: str, message: str, percent: int, err: str = None, report: list = None):
            has_fallback = any(getattr(s, 'is_fallback', False) for s in current_segments)
            serialized = []
            for seg in current_segments:
                serialized.append({
                    "segment_id": seg.segment_id,
                    "start": seg.start,
                    "end": seg.end,
                    "source_text": seg.source_text,
                    "target_text": seg.target_text,
                    "audio_path": seg.audio_path,
                    "is_fallback": getattr(seg, 'is_fallback', False)
                })
            engines_info = {
                "stt": self.settings.get("provider", {}).get("stt", "groq_whisper"),
                "translate": self.settings.get("provider", {}).get("translate", "groq_llm"),
                "tts": self.settings.get("provider", {}).get("tts", "azure_speech")
            }
            state_data = {
                "status": status,
                "progress": percent,
                "message": message,
                "segments": serialized,
                "alignmentReport": report or [],
                "has_fallback": has_fallback,
                "engines": engines_info,
                "error": err
            }
            try:
                with open(state_file, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, ensure_ascii=False)
            except Exception as ex:
                logger.error(f"Failed to write state: {ex}")

        def trigger_progress(message: str, percent: int):
            logger.info(f"[{percent}%] {message}")
            dump_state("running", message, percent)
            if on_progress:
                on_progress(message, percent)
                
        try:
            # 1. Initialization
            trigger_progress("Initializing STT, Translation, and TTS providers...", 5)
            
            retry_cfg = self.settings.get("retry", {})
            stt_name = self.settings.get("provider", {}).get("stt", "groq_whisper")
            if stt_name == "groq_whisper":
                stt_provider = GroqWhisperSTT(self.settings.get("stt", {}).get("groq_whisper", {}), retry_cfg)
            else:
                stt_provider = GeminiSTT(self.settings.get("stt", {}).get("gemini", {}), retry_cfg)

            translate_name = self.settings.get("provider", {}).get("translate", "groq_llm")
            if translate_name == "groq_llm":
                translate_provider = GroqTranslate(self.settings.get("translate", {}).get("groq_llm", {}), retry_cfg)
            else:
                translate_provider = GeminiTranslate(self.settings.get("translate", {}).get("gemini", {}), retry_cfg)

            tts_name = self.settings.get("provider", {}).get("tts", "azure_speech")
            if tts_name == "azure_speech":
                tts_provider = AzureSpeechTTS(self.settings.get("tts", {}).get("azure_speech", {}), retry_cfg)
            else:
                tts_provider = GeminiTTS(retry_cfg)
            
            trigger_progress(f"Providers successfully loaded: STT=[{stt_provider.name}], TRANSLATE=[{translate_provider.name}], TTS=[{tts_provider.name}]", 10)

            # 2. STT Phase
            trigger_progress("Transcribing original English audio file...", 20)
            segments = stt_provider.transcribe(audio_path)
            current_segments = segments
            trigger_progress(f"STT Phase completed. Generated {len(segments)} segment transcription blocks.", 40)

            if not segments:
                raise ValueError("STT phase returned 0 transcription segments.")

            # 3. Translation Phase
            trigger_progress("Translating transcription segments to Chinese with sliding context...", 50)
            segments = translate_provider.translate(segments)
            current_segments = segments
            trigger_progress("Translation Phase completed successfully.", 75)

            # 4. TTS Phase
            trigger_progress("Synthesizing localized Chinese voiceovers...", 75)
            
            def on_tts_done(idx, total):
                percent = 75 + int(20 * (idx / total))
                dump_state("running", f"Synthesizing audio segments: {idx}/{total}", percent)

            segments = tts_provider.synthesize(segments, self.output_dir, on_segment_done=on_tts_done)
            current_segments = segments
            trigger_progress("TTS Phase audio clips fully rendered.", 95)

            # 5. Alignment Timing Analysis
            trigger_progress("Running audio-duration timing alignment diagnostics...", 98)
            threshold = self.settings.get("align", {}).get("warning_threshold_ratio", 1.3)
            alignment_report = check_alignment(segments, self.output_dir, threshold)

            warnings = [r for r in alignment_report if r["warning"]]
            if warnings:
                msg = f"Pipeline finished. Found {len(warnings)} segments exceeding duration threshold."
            else:
                msg = "Pipeline completed flawlessly! All dubbed timings align perfectly with original video."
                
            trigger_progress(msg, 100)

            # Map segments back to standard dictionaries for JSON serialization
            serialized_segments = []
            has_fallback = False
            for seg in segments:
                if getattr(seg, 'is_fallback', False):
                    has_fallback = True
                serialized_segments.append({
                    "segment_id": seg.segment_id,
                    "start": seg.start,
                    "end": seg.end,
                    "source_text": seg.source_text,
                    "target_text": seg.target_text,
                    "audio_path": seg.audio_path,
                    "is_fallback": getattr(seg, 'is_fallback', False)
                })

            dump_state("completed", msg, 100, report=alignment_report)
            return {
                "success": True,
                "segments": serialized_segments,
                "alignmentReport": alignment_report,
                "has_fallback": has_fallback
            }

        except Exception as e:
            err_msg = str(e)
            trigger_progress(f"Pipeline crashed during execution: {err_msg}", 100)
            dump_state("error", f"Crashed: {err_msg}", 100, err=err_msg)
            return {
                "success": False,
                "segments": [],
                "alignmentReport": [],
                "error": err_msg
            }

def parse_toml_file(file_path: str) -> dict:
    if not os.path.exists(file_path):
        return {}
    try:
        import tomllib
        with open(file_path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        logger.warning("tomllib not found (requires Python 3.11+). Using empty settings.")
        return {}

if __name__ == "__main__":
    # Allow execution directly from CLI command
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <path_to_audio_mp3> [path_to_settings_toml] [output_directory]")
        sys.exit(1)
        
    input_audio = sys.argv[1]
    toml_path = sys.argv[2] if len(sys.argv) > 2 else "./settings.toml"
    output_directory = sys.argv[3] if len(sys.argv) > 3 else "./output"
    
    # Load dynamic settings or fallback
    settings = parse_toml_file(toml_path)
    if not settings:
        settings = {
            "provider": {
                "stt": "groq_whisper",
                "translate": "gemini",
                "tts": "azure_speech"
            },
            "stt": {
                "groq_whisper": {"api_key": "", "model": "whisper-large-v3-turbo"},
                "gemini": {"api_key": "", "model": "gemini-3.5-flash"}
            },
            "translate": {
                "gemini": {"api_key": "", "model": "gemini-3.5-flash"}
            },
            "tts": {
                "azure_speech": {"api_key": "", "region": "eastus", "voice": "zh-CN-XiaoxiaoNeural"},
                "gemini_tts": {"voice": "Kore"}
            },
            "retry": {
                "max_retries": 3,
                "base_delay": 1.0,
                "backoff_factor": 2.0,
                "max_delay": 30.0
            },
            "align": {
                "warning_threshold_ratio": 1.3
            }
        }
    
    pipeline = TranslatorPilotPipeline(settings, output_directory)
    result = pipeline.run(input_audio)
    
    # Save formatted JSON to file for convenient manual viewing
    os.makedirs(output_directory, exist_ok=True)
    out_json = os.path.join(output_directory, "pipeline_result.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
