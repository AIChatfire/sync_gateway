"""同步网关配置契约"""
from typing import Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class AuthConfig(BaseModel):
    type: Literal["bearer", "api_key", "none"] = "bearer"
    env: Optional[str] = None
    header_name: Optional[str] = None


class EndpointConfig(BaseModel):
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = "POST"
    path: str
    timeout: int = 120  # 同步任务默认 120s


class FieldRule(BaseModel):
    """声明式/表达式规则"""
    from_field: Optional[str] = Field(None, alias="from")
    const: Optional[Any] = None
    default: Optional[Any] = None
    map: Optional[Dict[str, Any]] = None
    expr: Optional[str] = None

    class Config:
        populate_by_name = True


class ProviderConfig(BaseModel):
    base_url: str
    auth: AuthConfig = AuthConfig()
    passthrough: bool = False  # 透传模式：零转换
    endpoints: Dict[str, EndpointConfig]  # 如 {"generate": {...}}
    request_map: Optional[Dict[str, FieldRule]] = None
    response_map: Optional[Dict[str, FieldRule]] = None
    request_script: Optional[str] = None
    response_script: Optional[str] = None


class GatewayConfig(BaseModel):
    version: str = "0.0.1"
    active: bool = True
    providers: Dict[str, ProviderConfig]
