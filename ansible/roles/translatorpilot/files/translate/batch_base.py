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
    """Base class for batched translation providers with shared cache and prompt logic.

    Subclasses implement _fetch_translations() to call their provider-specific API.
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
        """Call provider API and return a list of translation dicts."""
        pass

    def _parse_translation_json(self, candidate_text: str) -> List[Dict[str, Any]]:
        """Parse model JSON output, stripping markdown fences if present."""
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
