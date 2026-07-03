import logging
from typing import Callable, Optional, TypeVar

from retry import with_retry

logger = logging.getLogger("http")

T = TypeVar("T")


def bearer_json_headers(api_key: str) -> dict:
    """Standard JSON API headers with Bearer authentication."""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def bearer_headers(api_key: str) -> dict:
    """Bearer auth only (for form-data APIs)."""
    return {
        "Authorization": f"Bearer {api_key}",
    }


def run_with_http_retry(
    fn: Callable[[], T],
    retry_config: dict,
    label: str,
    role: str,
    on_error: Optional[Callable[[Exception], Exception]] = None,
) -> T:
    """Run an HTTP-backed operation with retry and consistent ImportError handling."""
    try:
        return with_retry(fn, retry_config, label)
    except ImportError:
        logger.error(f"[{role.upper()}] 'requests' library not found. Run 'pip install requests'.")
        raise RuntimeError("Fatal pipeline error: missing dependencies")
    except Exception as e:
        if on_error:
            raise on_error(e) from e
        raise
