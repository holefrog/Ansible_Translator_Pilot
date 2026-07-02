import time
import logging

logger = logging.getLogger("retry")

def with_retry(fn, retry_config: dict, label: str = "Operation"):
    max_retries = retry_config["max_retries"]
    base_delay = retry_config["base_delay"]
    backoff_factor = retry_config["backoff_factor"]
    max_delay = retry_config["max_delay"]

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
                # 提供更详细的错误信息
                if "timeout" in err_msg.lower() or "timed out" in err_msg.lower():
                    logger.error(f"[{label}] 网络超时：在 {max_retries} 次重试后仍然无法连接。请检查网络连接或稍后重试。错误: {err_msg}")
                else:
                    logger.error(f"[{label}] 操作失败：在 {max_retries} 次重试后仍然失败。错误: {err_msg}")
                raise e

            # Calculate exponential backoff
            delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)
            logger.warning(f"[{label}] 第 {attempt} 次尝试失败，{delay:.1f} 秒后重试... 错误: {err_msg}")
            time.sleep(delay)
