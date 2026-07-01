import uuid
from typing import List, Optional
from dataclasses import dataclass, field

@dataclass
class Segment:
    segment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    start: float = 0.0
    end: float = 0.0
    source_text: str = ""
    target_text: Optional[str] = None
    audio_path: Optional[str] = None
    context_window: Optional[List[str]] = None
    is_fallback: bool = False
