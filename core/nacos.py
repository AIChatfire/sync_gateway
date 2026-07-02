"""Nacos 配置监听 + 热更新 + 快照回滚"""
import os
import yaml
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from core.config import GatewayConfig


@dataclass
class ConfigSnapshot:
    version: str
    raw: str
    parsed: GatewayConfig
    timestamp: float


class NacosConfigManager:
    def __init__(
        self,
        server_addresses: Optional[str] = None,
        data_id: Optional[str] = None,
        group: str = "DEFAULT_GROUP",
        local_fallback: str = "./gateway.yaml",
        max_history: int = 5,
    ):
        self.server = server_addresses or os.getenv("NACOS_SERVER")
        self.data_id = data_id or os.getenv("NACOS_DATA_ID", "sync-gateway.yaml")
        self.group = group
        self.local_fallback = local_fallback
        self.max_history = int(os.getenv("CONFIG_MAX_HISTORY", max_history))
        self._history: List[ConfigSnapshot] = []
        self._current: Optional[ConfigSnapshot] = None
        self._listeners: List[Callable[[GatewayConfig], None]] = []
        self._error_listeners: List[Callable[[Exception, str], None]] = []
        self._nacos_client = None

    def add_listener(self, callback: Callable[[GatewayConfig], None]):
        self._listeners.append(callback)

    def add_error_listener(self, callback: Callable[[Exception, str], None]):
        self._error_listeners.append(callback)

    def start(self) -> GatewayConfig:
        """启动：先读本地兜底，再尝试 Nacos"""
        cfg = self._load_local()
        if self.server:
            try:
                from nacos import NacosClient
                self._nacos_client = NacosClient(
                    server_addresses=self.server,
                    namespace="public",
                )
                content = self._nacos_client.get_config(self.data_id, self.group)
                if content:
                    cfg = self._apply(content, source="nacos")
                self._nacos_client.add_config_watcher(
                    self.data_id, self.group, self._on_remote_change
                )
            except Exception as e:
                self._notify_error(e, "")
        return cfg

    def _load_local(self) -> GatewayConfig:
        with open(self.local_fallback, "r", encoding="utf-8") as f:
            content = f.read()
        return self._apply(content, source="local")

    def _on_remote_change(self, cfg):
        content = cfg.get("content", "")
        try:
            self._apply(content, source="nacos")
        except Exception as e:
            self._notify_error(e, content)

    def _apply(self, content: str, source: str) -> GatewayConfig:
        try:
            data = yaml.safe_load(content)
            parsed = GatewayConfig(**data)
        except Exception as e:
            if self._current:
                self._notify_error(e, content)
                return self._current.parsed
            raise RuntimeError(f"Config parse failed and no fallback: {e}")

        snapshot = ConfigSnapshot(
            version=parsed.version,
            raw=content,
            parsed=parsed,
            timestamp=__import__("time").time(),
        )
        self._history.insert(0, snapshot)
        if len(self._history) > self.max_history:
            self._history.pop()
        self._current = snapshot

        for cb in self._listeners:
            try:
                cb(parsed)
            except Exception as e:
                self._notify_error(e, content)
        return parsed

    def rollback(self, steps: int = 1) -> Optional[GatewayConfig]:
        if steps >= len(self._history):
            return None
        target = self._history[steps]
        self._history.insert(0, target)
        self._current = target
        for cb in self._listeners:
            cb(target.parsed)
        return target.parsed

    def history(self) -> List[Dict[str, Any]]:
        return [
            {"version": s.version, "timestamp": s.timestamp, "source": "nacos" if i == 0 else "history"}
            for i, s in enumerate(self._history)
        ]

    def _notify_error(self, error: Exception, raw: str):
        for cb in self._error_listeners:
            try:
                cb(error, raw)
            except Exception:
                pass
