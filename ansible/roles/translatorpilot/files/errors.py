def format_friendly_error(provider_name: str, model: str, error: Exception, operation: str = "翻译") -> RuntimeError:
    """Format error message with friendly Chinese descriptions for common errors."""
    err_msg = str(error)

    if "timeout" in err_msg.lower() or "timed out" in err_msg.lower():
        return RuntimeError(
            f"网络超时:{provider_name} API 响应超时。请检查网络连接或稍后重试。错误: {err_msg}"
        )
    if "401" in err_msg or "unauthorized" in err_msg.lower():
        return RuntimeError(
            f"认证失败:{provider_name} API Key 无效或已过期。请检查配置。错误: {err_msg}"
        )
    if "404" in err_msg or "not found" in err_msg.lower():
        return RuntimeError(
            f"模型不存在:配置的模型 '{model}' 在 {provider_name} API 上不可用。请检查模型名称。错误: {err_msg}"
        )
    return RuntimeError(f"{operation}失败:{err_msg}")
