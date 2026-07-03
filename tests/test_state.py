"""运行时状态隔离测试"""
from app.core.config import AuthConfig, EndpointConfig, GatewayConfig, ProviderConfig
from app.core.state import GatewayRuntimeState


def test_runtime_state_isolates_provider_transform_errors():
    cfg = GatewayConfig(
        providers={
            "good": ProviderConfig(
                base_url="http://good.example",
                auth=AuthConfig(type="none"),
                passthrough=True,
                endpoints={"generate": EndpointConfig(path="/v1/generate")},
            ),
            "bad": ProviderConfig(
                base_url="http://bad.example",
                auth=AuthConfig(type="none"),
                request_script="def not_transform(body): return body",
                endpoints={"generate": EndpointConfig(path="/v1/generate")},
            ),
        }
    )
    state = GatewayRuntimeState()

    errors = state.apply_config(cfg)
    snapshot = state.snapshot()

    assert "good" in snapshot.transformers
    assert "bad" not in snapshot.transformers
    assert "bad" in errors
    assert snapshot.config == cfg
