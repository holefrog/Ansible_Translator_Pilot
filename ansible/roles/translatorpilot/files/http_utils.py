import logging
from typing import Callable, Optional, TypeVar

from retry import with_retry

logger = logging.getLogger("http")

T = TypeVar("T")


def bearer_json_headers(api_key: str) -> dict:
    """
    生成带有 Bearer 认证的通用 JSON API 请求头。
    
    参数:
        api_key (str): 用于认证的 API 密钥。
    返回:
        dict: 包含 'Content-Type' 和 'Authorization' 的请求头字典。
    """
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def bearer_headers(api_key: str) -> dict:
    """
    生成仅包含 Bearer 认证的请求头 (主要适用于 multipart/form-data 类型的 API)。
    """
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
    """
    执行基于 HTTP 的操作并自带指数退避重试机制，同时一致地处理依赖导入异常。

    参数:
        fn: 需要被重试执行的无参闭包/函数。
        retry_config: 包含重试策略配置的字典 (需包含 max_retries, base_delay 等)。
        label: 用于日志输出的标签 (如 API 名称)。
        role: 角色名称，用于在缺失依赖时提示相关模块 (如 'TTS' 或 'STT')。
        on_error: 错误发生时的可选异常转换回调函数。
    
    返回:
        T: 成功执行函数后的返回值。
    """
    try:
        return with_retry(fn, retry_config, label)
    except ImportError:
        logger.error(f"[{role.upper()}] 'requests' library not found. Run 'pip install requests'.")
        raise RuntimeError("Fatal pipeline error: missing dependencies")
    except Exception as e:
        if on_error:
            raise on_error(e) from e
        raise
