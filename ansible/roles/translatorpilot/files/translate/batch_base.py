import os
import logging
from abc import abstractmethod
from typing import List, Dict, Any

from contracts import Segment
from cache import CacheManager
from errors import format_friendly_error
from http_utils import run_with_http_retry
from .base import TranslateProvider
from .common import (
    strip_markdown_fences,
    build_system_prompt,
    build_user_prompt,
    check_cache,
    load_from_cache,
    save_to_cache,
    map_translations_to_segments,
)

logger = logging.getLogger("translate")


class BatchedTranslateProvider(TranslateProvider):
    """
    支持批处理的翻译提供商基类，内置了缓存、提示词组装和重试逻辑。

    子类需要实现 `_fetch_translations()` 方法来真正调用提供商特有的 API。
    通过分批翻译，既能降低大语言模型处理长上下文遗忘的几率，又能防止单次 API 负载过大。
    """

    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config

    @property
    def additional_system_instruction(self) -> str:
        return ""

    @property
    def provider_display_name(self) -> str:
        return self.name

    def translate(self, segments: List[Segment]) -> List[Segment]:
        """
        分批翻译提取出的源文本。
        
        工作流:
        1. 根据 config 中的 batch_size 切分分段列表。
        2. 生成大语言模型专用的 JSON 系统提示词和用户提示词。
        3. 检查是否有本地缓存（如果启用了缓存）。
        4. 通过 API 调用语言模型，并强制要求返回严格的 JSON 对象。
        5. 将翻译结果的 ID 映射回相应的 Segment 中。
        """
        if not segments:
            return []

        model = self.config["model"]

        def run_api_call():
            cache = CacheManager("translate", os.getcwd())
            enable_cache = self.config.get("enable_cache", False)
            batch_size = int(self.config.get("batch_size", 20))

            for i in range(0, len(segments), batch_size):
                batch = segments[i : i + batch_size]
                items_to_translate = [
                    {"id": seg.segment_id, "text": seg.source_text}
                    for seg in batch
                ]

                base_system_instruction, system_instruction = build_system_prompt(
                    self.config, len(items_to_translate)
                )
                if self.additional_system_instruction:
                    system_instruction += "\n" + self.additional_system_instruction

                user_prompt = build_user_prompt(self.config, items_to_translate)
                cache_key = CacheManager.make_cache_key(
                    base_system_instruction, user_prompt, model
                )

                if check_cache(cache, cache_key, enable_cache):
                    logger.info(
                        f"[Translate] Translation cache hit for batch {i // batch_size + 1}!"
                    )
                    parsed_translations = load_from_cache(cache, cache_key)
                else:
                    parsed_translations = self._fetch_translations(
                        system_instruction, user_prompt, model
                    )
                    save_to_cache(cache, cache_key, parsed_translations, enable_cache)

                map_translations_to_segments(batch, parsed_translations)

            return segments

        def on_error(e: Exception) -> Exception:
            logger.error(
                f"[Translate] Failed {self.provider_display_name} translation: {e}."
            )
            return format_friendly_error(self.provider_display_name, model, e)

        return run_with_http_retry(
            run_api_call,
            self.retry_config,
            self.__class__.__name__,
            "translate",
            on_error=on_error,
        )

    @abstractmethod
    def _fetch_translations(
        self, system_instruction: str, user_prompt: str, model: str
    ) -> List[Dict[str, Any]]:
        """调用服务商 API 执行翻译，并返回按 ID 对应的字典列表。必须由子类实现。"""
        pass

    def _parse_translation_json(self, candidate_text: str) -> List[Dict[str, Any]]:
        """解析模型输出的 JSON 文本，去除可能存在的 Markdown 代码块包裹符。"""
        import json

        try:
            candidate_text = strip_markdown_fences(candidate_text)
            parsed_json = json.loads(candidate_text)
            return parsed_json.get("translations", [])
        except json.JSONDecodeError as e:
            logger.error(
                f"Failed to parse {self.provider_display_name} JSON: {candidate_text}"
            )
            raise Exception(
                f"{self.provider_display_name} output is not valid JSON: {e}"
            ) from e
