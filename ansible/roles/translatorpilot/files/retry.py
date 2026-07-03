import time
import logging

logger = logging.getLogger("retry")

def with_retry(fn, retry_config: dict, label: str = "Operation"):
    """
    执行带有指数退避 (Exponential Backoff) 机制的操作重试。
    如果遇到由于鉴权失败等不可恢复的异常，将直接抛出错误并终止重试。

    参数:
        fn: 待执行的可调用无参闭包对象。
        retry_config (dict): 包含重试相关参数的字典：
            - max_retries (int): 最大重试次数。
            - base_delay (float): 基础延迟等待时间 (秒)。
            - backoff_factor (float): 每次重试等待的倍数因子。
            - max_delay (float): 延迟等待的上限时间 (秒)。
        label (str): 日志输出中的操作标签。
        
    返回:
        fn() 执行成功的结果。
    """
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
