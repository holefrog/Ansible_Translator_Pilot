import os
import json
import logging
from typing import List
from contracts import Segment
from retry import with_retry
from .base import TranslateProvider
from cache import CacheManager
from .common import (
    strip_markdown_fences,
    build_system_prompt,
    build_user_prompt,
    get_cache_key,
    check_cache,
    load_from_cache,
    save_to_cache,
    map_translations_to_segments,
    format_friendly_error
)

logger = logging.getLogger("translate")


class OpenAICompatibleTranslate(TranslateProvider):
    """Base class for OpenAI-compatible translation providers.
    
    This class implements the common translation workflow for providers that use
    the OpenAI /chat/completions API shape (messages array, choices[0].message.content).
    
    Subclasses only need to override provider-specific configuration:
    - base_url: API endpoint URL
    - headers: HTTP headers (including Authorization)
    - use_response_format: Whether to send response_format: json_object
    - use_max_tokens: Whether to send max_tokens parameter
    - timeout: Request timeout in seconds
    - additional_system_instruction: Optional extra system instruction
    - provider_display_name: Human-readable name for error messages
    """
    
    def __init__(self, config: dict, retry_config: dict):
        self.config = config
        self.retry_config = retry_config
    
    @property
    def base_url(self) -> str:
        """Return the API base URL. Must be overridden by subclass."""
        raise NotImplementedError("Subclass must implement base_url")
    
    @property
    def headers(self) -> dict:
        """Return HTTP headers. Must be overridden by subclass."""
        raise NotImplementedError("Subclass must implement headers")
    
    @property
    def use_response_format(self) -> bool:
        """Whether to include response_format: json_object in payload."""
        return True
    
    @property
    def use_max_tokens(self) -> bool:
        """Whether to include max_tokens in payload."""
        return True
    
    @property
    def timeout(self) -> int:
        """Request timeout in seconds."""
        return 60
    
    @property
    def additional_system_instruction(self) -> str:
        """Optional additional system instruction to append."""
        return ""
    
    @property
    def provider_display_name(self) -> str:
        """Human-readable provider name for error messages."""
        return self.name
    
    def translate(self, segments: List[Segment]) -> List[Segment]:
        if not segments:
            return []
        
        api_key = self.config["api_key"]
        model = self.config["model"]
        
        if not api_key:
            logger.error(f"[Translate] {self.provider_display_name} API Key is missing. Cannot proceed.")
            raise RuntimeError("Fatal pipeline error")
        
        def run_api_call():
            import requests
            
            cache = CacheManager("translate", os.getcwd())
            enable_cache = self.config.get("enable_cache", False)
            batch_size = int(self.config.get("batch_size", 20))
            
            for i in range(0, len(segments), batch_size):
                batch = segments[i:i+batch_size]
                items_to_translate = [
                    {"id": seg.segment_id, "text": seg.source_text}
                    for seg in batch
                ]
                
                # Build prompts using common utilities
                base_system_instruction, system_instruction = build_system_prompt(
                    self.config, len(items_to_translate)
                )
                
                # Add any provider-specific system instruction
                if self.additional_system_instruction:
                    system_instruction += "\n" + self.additional_system_instruction
                
                user_prompt = build_user_prompt(self.config, items_to_translate)
                cache_key = get_cache_key(cache, base_system_instruction, user_prompt, model)
                
                # Check cache
                if check_cache(cache, cache_key, enable_cache):
                    logger.info(f"[Translate] Translation cache hit for batch {i//batch_size + 1}!")
                    parsed_translations = load_from_cache(cache, cache_key)
                else:
                    # Build payload
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": float(self.config.get("temperature", 0.3))
                    }
                    
                    if self.use_response_format:
                        payload["response_format"] = {"type": "json_object"}
                    
                    if self.use_max_tokens:
                        payload["max_tokens"] = int(self.config.get("max_tokens", 4096))
                    
                    # Make API call
                    response = requests.post(
                        self.base_url, 
                        headers=self.headers, 
                        json=payload, 
                        timeout=self.timeout
                    )
                    
                    if response.status_code != 200:
                        raise Exception(f"{self.provider_display_name} API Error {response.status_code}: {response.text}")
                    
                    resp_data = response.json()
                    candidate_text = resp_data["choices"][0]["message"]["content"]
                    
                    # Parse JSON with markdown fence stripping
                    try:
                        candidate_text = strip_markdown_fences(candidate_text)
                        parsed_json = json.loads(candidate_text)
                        parsed_translations = parsed_json.get("translations", [])
                        save_to_cache(cache, cache_key, parsed_translations, enable_cache)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse {self.provider_display_name} JSON: {candidate_text}")
                        raise Exception(f"{self.provider_display_name} output is not valid JSON: {e}")
                
                # Map translations back to segments
                map_translations_to_segments(batch, parsed_translations)
            
            return segments
        
        try:
            return with_retry(run_api_call, self.retry_config, f"{self.__class__.__name__}")
        except ImportError:
            logger.error("[Translate] 'requests' library not found.")
            raise RuntimeError("Fatal pipeline error")
        except Exception as e:
            logger.error(f"[Translate] Failed {self.provider_display_name} translation: {e}.")
            raise format_friendly_error(self.provider_display_name, model, e)
