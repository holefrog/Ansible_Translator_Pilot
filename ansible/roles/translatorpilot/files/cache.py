import os
import hashlib
import shutil
import json
import logging

logger = logging.getLogger("cache")


class CacheManager:
    """通用缓存管理器，支持文件和 JSON 数据缓存"""

    def __init__(self, cache_type: str, output_dir: str):
        """
        初始化缓存管理器
        
        Args:
            cache_type: 缓存类型，如 'translate' 或 'wav'
            output_dir: 输出目录，缓存目录将创建在其父目录下
        """
        self.cache_type = cache_type
        self.cache_dir = os.path.join(os.path.dirname(output_dir), "cache", cache_type)
        os.makedirs(self.cache_dir, exist_ok=True)

    @staticmethod
    def make_cache_key(*args) -> str:
        """
        基于多个参数生成缓存 key（无需实例化 CacheManager）

        Args:
            *args: 用于生成 key 的参数，会被转换为字符串拼接

        Returns:
            MD5 哈希值作为缓存 key
        """
        cache_string = "_".join(str(arg) for arg in args)
        return hashlib.md5(cache_string.encode("utf-8")).hexdigest()

    def get_cache_key(self, *args) -> str:
        """基于多个参数生成缓存 key（实例方法，委托给 make_cache_key）。"""
        return self.make_cache_key(*args)

    def get_file_path(self, cache_key: str, extension: str = "") -> str:
        """
        获取缓存文件路径
        
        Args:
            cache_key: 缓存 key
            extension: 文件扩展名（如 '.json', '.wav'）
            
        Returns:
            完整的缓存文件路径
        """
        if not extension.startswith("."):
            extension = f".{extension}"
        return os.path.join(self.cache_dir, f"{cache_key}{extension}")

    def exists(self, cache_key: str, extension: str = "") -> bool:
        """检查缓存是否存在"""
        cache_path = self.get_file_path(cache_key, extension)
        return os.path.exists(cache_path)

    def load_json(self, cache_key: str) -> dict:
        """
        从缓存加载 JSON 数据
        
        Args:
            cache_key: 缓存 key
            
        Returns:
            缓存的 JSON 数据
            
        Raises:
            FileNotFoundError: 缓存不存在
            json.JSONDecodeError: 缓存数据不是有效的 JSON
        """
        cache_path = self.get_file_path(cache_key, ".json")
        if not os.path.exists(cache_path):
            raise FileNotFoundError(f"Cache not found: {cache_path}")
        
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_json(self, cache_key: str, data: dict) -> None:
        """
        保存 JSON 数据到缓存
        
        Args:
            cache_key: 缓存 key
            data: 要保存的 JSON 数据
        """
        cache_path = self.get_file_path(cache_key, ".json")
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def copy_file(self, cache_key: str, source_path: str, extension: str = "") -> None:
        """
        将文件复制到缓存
        
        Args:
            cache_key: 缓存 key
            source_path: 源文件路径
            extension: 文件扩展名
        """
        cache_path = self.get_file_path(cache_key, extension)
        shutil.copy2(source_path, cache_path)

    def copy_from_cache(self, cache_key: str, target_path: str, extension: str = "") -> None:
        """
        从缓存复制文件到目标路径
        
        Args:
            cache_key: 缓存 key
            target_path: 目标文件路径
            extension: 文件扩展名
            
        Raises:
            FileNotFoundError: 缓存不存在
        """
        cache_path = self.get_file_path(cache_key, extension)
        if not os.path.exists(cache_path):
            raise FileNotFoundError(f"Cache not found: {cache_path}")
        
        shutil.copy2(cache_path, target_path)

    def clear(self) -> None:
        """清空所有缓存"""
        if os.path.exists(self.cache_dir):
            for filename in os.listdir(self.cache_dir):
                file_path = os.path.join(self.cache_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            logger.info(f"[Cache] Cleared all cache in {self.cache_dir}")
