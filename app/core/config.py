"""同步网关配置契约"""
from typing import Dict, Any, Optional, Literal, List
from pydantic import BaseModel, Field, ConfigDict, model_validator

DEFAULT_ENDPOINT_NAME = "generate"


class AuthConfig(BaseModel):
    type: Literal["bearer", "api_key", "none"] = "bearer"
    # 兼容旧配置字段；API key 当前只从入口请求 headers 获取，不再读取服务端 env。
    env: Optional[str] = None
    header_name: Optional[str] = None


class EndpointConfig(BaseModel):
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = "POST"
    path: str
    timeout: int = 120  # 同步任务默认 120s


class ResilienceConfig(BaseModel):
    """Provider 级韧性配置，用于隔离慢/坏下游。"""

    max_concurrency: int = Field(100, ge=1)
    failure_threshold: int = Field(5, ge=1)
    recovery_seconds: int = Field(30, ge=1)
    retry_attempts: int = Field(0, ge=0, le=3)
    retry_backoff_seconds: float = Field(0.25, ge=0)
    retry_on_status: List[int] = Field(default_factory=lambda: [502, 503, 504])


class FieldRule(BaseModel):
    """声明式/表达式规则"""
    from_field: Optional[str] = Field(None, alias="from")
    const: Optional[Any] = None
    default: Optional[Any] = None
    map: Optional[Dict[str, Any]] = None
    expr: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class ProviderConfig(BaseModel):
    base_url: str
    auth: AuthConfig = Field(default_factory=AuthConfig)
    passthrough: bool = False  # 透传模式：零转换
    # 单端点短写：endpoint 会被归一成 endpoints.generate
    endpoint: Optional[EndpointConfig] = None
    endpoints: Dict[str, EndpointConfig] = Field(default_factory=dict)
    resilience: ResilienceConfig = Field(default_factory=ResilienceConfig)
    request_map: Optional[Dict[str, FieldRule]] = None
    response_map: Optional[Dict[str, FieldRule]] = None
    request_script: Optional[str] = None
    response_script: Optional[str] = None

    @model_validator(mode="after")
    def normalize_default_endpoint(self):
        if self.endpoint and DEFAULT_ENDPOINT_NAME not in self.endpoints:
            self.endpoints[DEFAULT_ENDPOINT_NAME] = self.endpoint
        if not self.endpoints:
            raise ValueError("provider must define endpoint or endpoints")
        return self


class GatewayConfig(BaseModel):
    version: str = "0.0.1"
    active: bool = True
    providers: Dict[str, ProviderConfig]
    # 动态路由表：
    # - 短写 List[str]：客户端请求路径列表，自动映射到 generate
    # - 完整 Dict[str, str]：客户端请求路径 -> 逻辑端点名（对应 provider.endpoints 的 key）
    # 同一个逻辑端点名下，不同 provider 可各自配置不同的下游目标路径（见 ProviderConfig.endpoints）
    # 新增/修改来源路径别名只需编辑此表，无需改代码，改完 Nacos 推送即可热更新
    routes: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_routes(cls, data):
        if not isinstance(data, dict):
            return data
        routes = data.get("routes")
        if isinstance(routes, list):
            data = dict(data)
            data["routes"] = {path: DEFAULT_ENDPOINT_NAME for path in routes}
        return data

    @model_validator(mode="after")
    def validate_routes(self):
        endpoint_names = {
            endpoint_name
            for provider in self.providers.values()
            for endpoint_name in provider.endpoints.keys()
        }
        unknown = sorted(set(self.routes.values()) - endpoint_names)
        if unknown:
            raise ValueError(f"routes reference unknown endpoint(s): {unknown}")

        invalid_paths = sorted(path for path in self.routes if not path.startswith("/"))
        if invalid_paths:
            raise ValueError(f"route paths must start with '/': {invalid_paths}")
        return self
