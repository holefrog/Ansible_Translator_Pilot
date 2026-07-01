import time
import logging

logger = logging.getLogger("retry")

def with_retry(fn, retry_config: dict, label: str = "Operation"):
    max_retries = retry_config.get("max_retries", 3)
    base_delay = retry_config.get("base_delay", 1.0)
    backoff_factor = retry_config.get("backoff_factor", 2.0)
    max_delay = retry_config.get("max_delay", 30.0)
    
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:
            attempt += 1
            err_msg = str(e)
            
            # Identify non-retryable exceptions (like 401 Unauthorized, invalid keys, etc)
            is_unauthorized = any(x in err_msg.lower() for x in ["401", "unauthorized", "invalid api key", "forbidden", "403"])
            
            if is_unauthorized:
                logger.error(f"[{label}] Non-retryable authentication error on attempt {attempt}: {err_msg}")
                raise e
                
            if attempt > max_retries:
                logger.error(f"[{label}] Operation failed permanently after {attempt} attempts.")
                raise e
                
            # Calculate exponential backoff
            delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)
            logger.warning(f"[{label}] Attempt {attempt} failed. Retrying in {delay:.1f} seconds... Error: {err_msg}")
            time.sleep(delay)
