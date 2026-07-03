import os
import sys
import json
import time
import logging
from typing import Callable, Optional
from contracts import Segment
from stt import GroqWhisperSTT, GeminiSTT
from translate import TranslateProvider, GeminiTranslate, GroqTranslate, NvidiaTranslate, OpenAITranslate, MistralTranslate
from tts import AzureSpeechTTS, GeminiTTS, SherpaOnnxTTS, NvidiaMagpieTTS
from align_check import check_alignment

class ColorFormatter(logging.Formatter):
    """
    自定义的控制台日志格式化器，支持在终端输出带颜色的高亮文本。
    特别针对错误和警告级别的日志添加红色或黄色以提升可读性。
    """
    RED = '\033[91m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'
    
    def format(self, record):
        s = super().format(record)
        
        # Explicitly highlight specific error keywords in RED
        s = s.replace("Pipeline Error", f"{self.RED}Pipeline Error{self.RESET}")
        s = s.replace("Fatal pipeline error", f"{self.RED}Fatal pipeline error{self.RESET}")
        
        if record.levelno == logging.ERROR:
            return f"{self.RED}{s}{self.RESET}"
        elif record.levelno == logging.WARNING:
            # If warning, yellow, but ensure red keywords stay red by re-applying yellow around them
            s_colored = f"{self.YELLOW}{s}{self.RESET}"
            s_colored = s_colored.replace(self.RESET, f"{self.RESET}{self.YELLOW}")
            # The very end will have two resets or something harmless, but the keyword will be red
            return s_colored
        
        return s

# Set up logging configuration
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(ColorFormatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
logging.root.handlers = [handler]
logging.root.setLevel(logging.WARNING)
logger = logging.getLogger("pipeline")

class TranslatorPilotPipeline:
    """
    Translator Pilot 核心管道控制类。
    负责协调语音识别 (STT)、大语言模型翻译 (Translate) 以及语音合成 (TTS) 三个阶段的工作流，
    并维护状态的序列化与进度报告。
    """
    def __init__(self, settings: dict, output_dir: str):
        self.settings = settings
        self.output_dir = output_dir
        self._validate_config()
    
    def _validate_config(self):
        """
        验证配置文件中是否包含所有必需的配置项和提供商密钥。
        如果配置缺失，将抛出 ValueError。
        """
        def require_section(section: str, keys: list):
            if section not in self.settings:
                raise ValueError(f"Missing required configuration section: {section}")
            for key in keys:
                if key not in self.settings[section]:
                    raise ValueError(f"Missing required configuration key: {section}.{key}")

        def require_keys(data: dict, keys: list, path: str):
            for key in keys:
                if key not in data:
                    raise ValueError(f"Missing required configuration key: {path}.{key}")

        require_section("provider", ["stt", "translate", "tts"])
        require_section("retry", ["max_retries", "base_delay", "backoff_factor", "max_delay"])
        require_section("align", ["warning_threshold_ratio"])
        require_section("rate_limit", ["tts_rps"])

        stt_name = self.settings["provider"]["stt"]
        require_keys(self.settings.get("stt", {}).get("common", {}), ["timeout", "prompt"], "stt.common")
        require_keys(self.settings.get("stt", {}).get(stt_name, {}), ["api_key", "model"], f"stt.{stt_name}")

        translate_name = self.settings["provider"]["translate"]
        require_keys(
            self.settings.get("translate", {}).get("common", {}),
            ["system_prompt", "style_guide", "user_prompt", "timeout", "batch_size",
             "temperature", "max_tokens", "enable_cache"],
            "translate.common",
        )
        require_keys(
            self.settings.get("translate", {}).get(translate_name, {}),
            ["api_key", "model"],
            f"translate.{translate_name}",
        )

        tts_name = self.settings["provider"]["tts"]
        require_keys(self.settings.get("tts", {}).get("common", {}), ["timeout", "enable_cache"], "tts.common")
        tts_provider_keys = {
            "azure_speech": ["api_key", "region", "voice"],
            "gemini_tts": ["api_key", "model", "voice"],
            "nvidia_magpie": ["api_key", "language", "voice", "sample_rate_hz"],
            "sherpa_onnx": ["model_dir", "vocoder_path", "num_threads", "volume_gain"],
        }
        if tts_name not in tts_provider_keys:
            raise ValueError(f"Unknown TTS provider: {tts_name}")
        require_keys(
            self.settings.get("tts", {}).get(tts_name, {}),
            tts_provider_keys[tts_name],
            f"tts.{tts_name}",
        )

    def run(self, audio_path: str, on_progress: Optional[Callable[[str, int], None]] = None) -> dict:
        """
        执行完整的翻译管道工作流。
        
        流程:
        1. 初始化 STT、Translate 和 TTS 提供商实例
        2. 执行 STT：将英文语音转录为带时间戳的文本段落
        3. 执行 Translate：使用大语言模型翻译字幕
        4. 执行 TTS：合成中文配音音频
        5. 运行对齐分析，检查配音音频是否过长
        
        参数:
            audio_path (str): 输入的原始音频文件路径。
            on_progress (Callable): 用于报告处理进度的回调函数 (可选)。
            
        返回:
            dict: 包含执行结果、合成片段列表及对齐报告的字典。
        """
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
            # Get provider names
            stt_provider = self.settings["provider"]["stt"]
            translate_provider = self.settings["provider"]["translate"]
            tts_provider = self.settings["provider"]["tts"]

            # Get model names for display
            stt_model = self.settings.get("stt", {}).get(stt_provider, {}).get("model", "")
            translate_model = self.settings.get("translate", {}).get(translate_provider, {}).get("model", "")
            tts_model = self.settings.get("tts", {}).get(tts_provider, {}).get("model", "")

            # For Sherpa-ONNX, use model_dir as model name
            if tts_provider == "sherpa_onnx":
                tts_model = self.settings.get("tts", {}).get("sherpa_onnx", {}).get("model_dir", "").split("/")[-1] if self.settings.get("tts", {}).get("sherpa_onnx", {}).get("model_dir") else ""

            engines_info = {
                "stt": f"{stt_provider} ({stt_model})" if stt_model else stt_provider,
                "translate": f"{translate_provider} ({translate_model})" if translate_model else translate_provider,
                "tts": f"{tts_provider} ({tts_model})" if tts_model else tts_provider
            }
            state_data = {
                "status": status,
                "progress": percent,
                "message": message,
                "segments": serialized,
                "alignmentReport": report or [],
                "has_fallback": has_fallback,
                "engines": engines_info,
                "timings": timings,
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
            timings = {"stt": None, "translate": None, "tts": None}
            trigger_progress("Initializing STT, Translation, and TTS providers...", 5)
            
            retry_cfg = self.settings["retry"]
            stt_name = self.settings["provider"]["stt"]
            stt_common = self.settings.get("stt", {}).get("common", {})
            stt_provider_cfg = self.settings.get("stt", {}).get(stt_name, {})
            stt_cfg = {**stt_common, **stt_provider_cfg}
            
            if stt_name == "groq_whisper":
                stt_provider = GroqWhisperSTT(stt_cfg, retry_cfg)
            else:
                stt_provider = GeminiSTT(stt_cfg, retry_cfg)

            translate_name = self.settings["provider"]["translate"]
            translate_common = self.settings.get("translate", {}).get("common", {})
            translate_provider_cfg = self.settings.get("translate", {}).get(translate_name, {})
            translate_cfg = {**translate_common, **translate_provider_cfg}
            
            if translate_name == "groq_llm":
                translate_provider = GroqTranslate(translate_cfg, retry_cfg)
            elif translate_name == "nvidia_llm":
                translate_provider = NvidiaTranslate(translate_cfg, retry_cfg)
            elif translate_name == "openai":
                translate_provider = OpenAITranslate(translate_cfg, retry_cfg)
            elif translate_name == "mistral":
                translate_provider = MistralTranslate(translate_cfg, retry_cfg)
            else:
                translate_provider = GeminiTranslate(translate_cfg, retry_cfg)

            tts_name = self.settings["provider"]["tts"]
            tts_common = self.settings.get("tts", {}).get("common", {})
            tts_provider_cfg = self.settings.get("tts", {}).get(tts_name, {})
            tts_cfg = {**tts_common, **tts_provider_cfg}
            
            if tts_name == "azure_speech":
                tts_provider = AzureSpeechTTS(tts_cfg, retry_cfg)
            elif tts_name == "sherpa_onnx":
                tts_provider = SherpaOnnxTTS(tts_cfg)
            elif tts_name == "nvidia_magpie":
                tts_provider = NvidiaMagpieTTS(tts_cfg, retry_cfg)
            else:
                tts_provider = GeminiTTS(tts_cfg, retry_cfg)
            
            trigger_progress(f"Providers successfully loaded: STT=[{stt_provider.name}], TRANSLATE=[{translate_provider.name}], TTS=[{tts_provider.name}]", 10)

            # 2. STT Phase
            trigger_progress("Transcribing original English audio file...", 20)
            t0_stt = time.time()
            segments = stt_provider.transcribe(audio_path)
            timings["stt"] = round(time.time() - t0_stt, 1)
            current_segments = segments
            trigger_progress(f"STT Phase completed. Generated {len(segments)} segment transcription blocks.", 40)

            if not segments:
                raise ValueError("STT phase returned 0 transcription segments.")

            # 3. Translation Phase
            trigger_progress("Translating transcription segments to Chinese with sliding context...", 50)
            t0_translate = time.time()
            try:
                segments = translate_provider.translate(segments)
            except Exception as e:
                err_msg = str(e)
                logger.error(f"Translation phase failed: {err_msg}")
                dump_state("error", f"翻译阶段失败: {err_msg}", 60, err=err_msg)
                raise
            timings["translate"] = round(time.time() - t0_translate, 1)
            current_segments = segments
            trigger_progress("Translation Phase completed successfully.", 75)

            # 4. TTS Phase
            trigger_progress("Synthesizing localized Chinese voiceovers...", 75)
            threshold = self.settings["align"]["warning_threshold_ratio"]

            t0_tts = time.time()
            def on_tts_done(idx, total):
                timings["tts"] = round(time.time() - t0_tts, 1)
                percent = 75 + int(20 * (idx / total))
                temp_report = check_alignment(segments, self.output_dir, threshold)
                dump_state("running", f"Synthesizing audio segments: {idx}/{total}", percent, report=temp_report)

            segments = tts_provider.synthesize(segments, self.output_dir, on_segment_done=on_tts_done)
            current_segments = segments
            trigger_progress("TTS Phase audio clips fully rendered.", 95)

            # 5. Alignment Timing Analysis
            trigger_progress("Running audio-duration timing alignment diagnostics...", 98)
            threshold = self.settings["align"]["warning_threshold_ratio"]
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
    """
    解析并加载 TOML 配置文件。
    优先尝试 Python 3.11+ 内置的 tomllib，如果不存在则回退至第三方的 toml 库。
    """
    if not os.path.exists(file_path):
        logger.error(f"Configuration file not found: {file_path}")
        sys.exit(1)
    try:
        import tomllib
        with open(file_path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        try:
            import toml
            with open(file_path, "r", encoding="utf-8") as f:
                return toml.load(f)
        except ImportError:
            logger.error("No TOML parser available. Please use Python 3.11+ or install 'toml' package.")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to parse TOML file {file_path}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Allow execution directly from CLI command
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <path_to_audio_mp3> [path_to_settings_toml] [output_directory]")
        sys.exit(1)
        
    input_audio = sys.argv[1]
    toml_path = sys.argv[2] if len(sys.argv) > 2 else "./settings.toml"
    output_directory = sys.argv[3] if len(sys.argv) > 3 else "./output"
    
    # Load dynamic settings
    try:
        settings = parse_toml_file(toml_path)
    except SystemExit:
        # parse_toml_file already called sys.exit, re-raise to ensure exit
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    if not settings:
        print(f"Error: Failed to load valid configuration from {toml_path}.")
        sys.exit(1)
    
    pipeline = TranslatorPilotPipeline(settings, output_directory)
    result = pipeline.run(input_audio)
    
    # Save formatted JSON to file for convenient manual viewing
    os.makedirs(output_directory, exist_ok=True)
    out_json = os.path.join(output_directory, "pipeline_result.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
