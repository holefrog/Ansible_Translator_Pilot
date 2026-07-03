def format_friendly_error(provider_name: str, model: str, error: Exception, operation: str = "翻译") -> RuntimeError:
    """
    将底层异常格式化为用户友好的中文错误信息。
    主要针对网络超时、API 认证失败或模型不存在等常见异常进行人性化解释。

    参数:
        provider_name (str): 服务提供商名称 (例如: 'Groq', 'Gemini')。
        model (str): 当前使用的模型名称。
        error (Exception): 抛出的原始异常对象。
        operation (str): 操作类型描述，默认为 '翻译'。
    
    返回:
        RuntimeError: 包含格式化后中文错误提示的运行时异常对象。
    """
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
