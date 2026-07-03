"""动态路由表解析测试"""
import pytest
from pydantic import ValidationError

from app.core.config import GatewayConfig, ProviderConfig, EndpointConfig, AuthConfig
from app.main import resolve_endpoint_name


def _make_config(routes):
    return GatewayConfig(
        providers={
            "p1": ProviderConfig(
                base_url="http://example.com",
                auth=AuthConfig(type="none"),
                endpoints={"generate": EndpointConfig(path="/v1/images/generations")},
            ),
        },
        routes=routes,
    )


def test_resolve_multiple_aliases_to_same_endpoint():
    """多个来源路径别名都应解析到同一个逻辑端点名"""
    cfg = _make_config(
        {
            "/v1/image-task/generations": "generate",
            "/v1/tasks/generations": "generate",
            "/v1/images/generations": "generate",
            "/v1/image/generations": "generate",
        }
    )
    for path in [
        "/v1/image-task/generations",
        "/v1/tasks/generations",
        "/v1/images/generations",
        "/v1/image/generations",
    ]:
        assert resolve_endpoint_name(cfg, path) == "generate"


def test_resolve_unknown_path_returns_none():
    """未在 routes 表中配置的动态路径不应隐式转发。"""
    cfg = _make_config({})
    assert resolve_endpoint_name(cfg, "/some/unmapped/path") is None


def test_routes_list_shorthand_maps_to_generate():
    """routes 可短写成入口路径列表，默认映射到 generate。"""
    cfg = _make_config(["/v1/images/generations", "/api/v3/images/generations"])

    assert cfg.routes == {
        "/v1/images/generations": "generate",
        "/api/v3/images/generations": "generate",
    }
    assert resolve_endpoint_name(cfg, "/v1/images/generations") == "generate"


def test_provider_endpoint_shorthand_maps_to_generate_endpoint():
    provider = ProviderConfig(
        base_url="http://example.com",
        auth=AuthConfig(type="none"),
        endpoint=EndpointConfig(path="/api/v3/images/generations", timeout=180),
    )

    assert provider.endpoints["generate"].path == "/api/v3/images/generations"
    assert provider.endpoints["generate"].timeout == 180


def test_different_providers_can_target_different_downstream_paths():
    """同一逻辑端点名下，不同 provider 的目标路径可以不同"""
    cfg = GatewayConfig(
        providers={
            "provider_images": ProviderConfig(
                base_url="http://a.com",
                auth=AuthConfig(type="none"),
                endpoints={"generate": EndpointConfig(path="/v1/images/generations")},
            ),
            "provider_image": ProviderConfig(
                base_url="http://b.com",
                auth=AuthConfig(type="none"),
                endpoints={"generate": EndpointConfig(path="/v1/image/generations")},
            ),
        },
        routes={"/v1/image-task/generations": "generate", "/v1/tasks/generations": "generate"},
    )
    assert cfg.providers["provider_images"].endpoints["generate"].path == "/v1/images/generations"
    assert cfg.providers["provider_image"].endpoints["generate"].path == "/v1/image/generations"


def test_config_rejects_route_to_unknown_endpoint():
    """routes 只能指向至少一个 provider 已声明的逻辑端点。"""
    with pytest.raises(ValidationError):
        _make_config({"/v1/unknown": "missing_endpoint"})


def test_config_rejects_route_without_leading_slash():
    with pytest.raises(ValidationError):
        _make_config({"v1/no-leading-slash": "generate"})
