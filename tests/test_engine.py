"""转换引擎基础测试"""
from app.core.config import ProviderConfig, EndpointConfig, AuthConfig, FieldRule
from app.core.engine import TransformEngine


def test_passthrough():
    provider = ProviderConfig(
        base_url="http://example.com",
        auth=AuthConfig(type="none"),
        passthrough=True,
        endpoints={"generate": EndpointConfig(path="/v1/gen")},
    )
    engine = TransformEngine(provider)
    body = {"prompt": "cat"}
    assert engine.transform_request(body) == body
    assert engine.transform_response(body) == body


def test_declarative_request():
    provider = ProviderConfig(
        base_url="http://example.com",
        auth=AuthConfig(type="none"),
        endpoints={"generate": EndpointConfig(path="/v1/gen")},
        request_map={
            "model": FieldRule(const="seedance-image"),
            "input.prompt": FieldRule(from_field="prompt"),
            "input.width": FieldRule(from_field="width", default=1024),
        },
    )
    engine = TransformEngine(provider)
    result = engine.transform_request({"prompt": "cat"})
    assert result == {"model": "seedance-image", "input": {"prompt": "cat", "width": 1024}}


def test_declarative_response():
    provider = ProviderConfig(
        base_url="http://example.com",
        auth=AuthConfig(type="none"),
        endpoints={"generate": EndpointConfig(path="/v1/gen")},
        response_map={
            "image_url": FieldRule(from_field="output.image_url"),
        },
    )
    engine = TransformEngine(provider)
    result = engine.transform_response({"output": {"image_url": "http://x.png"}})
    assert result == {"image_url": "http://x.png"}


def test_script_transform():
    provider = ProviderConfig(
        base_url="http://example.com",
        auth=AuthConfig(type="none"),
        endpoints={"generate": EndpointConfig(path="/v1/gen")},
        request_script="def transform(body): return {'x': body.get('y', 0) + 1}",
    )
    engine = TransformEngine(provider)
    assert engine.transform_request({"y": 2}) == {"x": 3}
