"""四模态转换引擎：透传 / 声明式 / 表达式 / 脚本"""
import copy
from typing import Dict, Any, Optional, Callable
from app.core.config import ProviderConfig, FieldRule


class TransformEngine:
    """为每个 Provider 构建请求/响应转换器"""

    def __init__(self, provider: ProviderConfig):
        self.provider = provider
        self._req_func: Optional[Callable] = None
        self._resp_func: Optional[Callable] = None
        self._build()

    def _build(self):
        cfg = self.provider
        # 透传模式：零转换
        if cfg.passthrough:
            self._req_func = lambda body: body
            self._resp_func = lambda body: body
            return

        # 请求转换器
        if cfg.request_script:
            self._req_func = self._compile_script(cfg.request_script)
        elif cfg.request_map:
            self._req_func = self._build_declarative(cfg.request_map)
        else:
            self._req_func = lambda body: body

        # 响应转换器
        if cfg.response_script:
            self._resp_func = self._compile_script(cfg.response_script)
        elif cfg.response_map:
            self._resp_func = self._build_declarative(cfg.response_map)
        else:
            self._resp_func = lambda body: body

    @staticmethod
    def _compile_script(code: str) -> Callable[[Dict], Dict]:
        """执行脚本提取 transform 函数对象"""
        local_ns: Dict[str, Any] = {}
        exec(code, {"__builtins__": {}}, local_ns)
        if "transform" not in local_ns:
            raise ValueError('Script must define "transform(body)"')
        return local_ns["transform"]

    def _build_declarative(self, mapping: Dict[str, FieldRule]) -> Callable[[Dict], Dict]:
        """构建声明式+表达式混合转换器"""
        rules = []
        for target_path, rule in mapping.items():
            rules.append((target_path, rule))

        def transformer(body: Dict[str, Any]) -> Dict[str, Any]:
            result: Dict[str, Any] = {}
            for target_path, rule in rules:
                value = self._resolve_rule(body, rule)
                self._set_path(result, target_path, value)
            return result
        return transformer

    @staticmethod
    def _get_path(obj: Dict, path: str) -> Any:
        """按点号路径读取嵌套 dict"""
        keys = path.split(".")
        for k in keys:
            if not isinstance(obj, dict) or k not in obj:
                return None
            obj = obj[k]
        return obj

    def _resolve_rule(self, body: Dict[str, Any], rule: FieldRule) -> Any:
        # 表达式优先
        if rule.expr:
            return eval(rule.expr, {"__builtins__": {}}, {"body": body})
        # 常量
        if rule.const is not None:
            return rule.const
        # 字段提取（支持嵌套路径）
        raw = self._get_path(body, rule.from_field) if rule.from_field else rule.default
        if raw is None and rule.default is not None:
            raw = rule.default
        # 枚举映射
        if rule.map and raw in rule.map:
            return rule.map[raw]
        return raw

    @staticmethod
    def _set_path(obj: Dict, path: str, value: Any):
        """按点号路径写入嵌套 dict"""
        keys = path.split(".")
        for k in keys[:-1]:
            obj = obj.setdefault(k, {})
        obj[keys[-1]] = value

    def transform_request(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._req_func(body)

    def transform_response(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._resp_func(body)
