"""网关运行时状态。

配置热更新可能来自 Nacos 后台线程，而请求处理运行在 ASGI 事件循环中。
这个模块把配置、转换器和配置错误收在一个可快照读取的状态对象里，避免入口
模块到处读写全局 dict。
"""
from dataclasses import dataclass
from threading import RLock
from time import time
from typing import Dict, Optional

from app.core.config import GatewayConfig
from app.core.engine import TransformEngine


@dataclass(frozen=True)
class RuntimeSnapshot:
    config: Optional[GatewayConfig]
    transformers: Dict[str, TransformEngine]
    provider_errors: Dict[str, str]
    loaded_at: Optional[float]
    last_config_error: Optional[str]


class GatewayRuntimeState:
    def __init__(self):
        self._lock = RLock()
        self._config: Optional[GatewayConfig] = None
        self._transformers: Dict[str, TransformEngine] = {}
        self._provider_errors: Dict[str, str] = {}
        self._loaded_at: Optional[float] = None
        self._last_config_error: Optional[str] = None

    def apply_config(self, cfg: GatewayConfig) -> Dict[str, str]:
        """构建新 Provider 转换器并原子替换运行时配置。

        单个 Provider 构建失败会被隔离到 provider_errors，其他 Provider 继续可用。
        """
        new_transformers: Dict[str, TransformEngine] = {}
        new_errors: Dict[str, str] = {}
        for name, provider in cfg.providers.items():
            try:
                new_transformers[name] = TransformEngine(provider)
            except Exception as exc:
                new_errors[name] = str(exc)

        with self._lock:
            self._config = cfg
            self._transformers = new_transformers
            self._provider_errors = new_errors
            self._loaded_at = time()
            self._last_config_error = None
        return new_errors

    def record_config_error(self, error: Exception) -> None:
        with self._lock:
            self._last_config_error = str(error)

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return RuntimeSnapshot(
                config=self._config,
                transformers=dict(self._transformers),
                provider_errors=dict(self._provider_errors),
                loaded_at=self._loaded_at,
                last_config_error=self._last_config_error,
            )
