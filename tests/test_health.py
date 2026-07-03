"""健康检查聚合语义测试"""
from app import main
from app.core.config import AuthConfig, EndpointConfig, GatewayConfig, ProviderConfig


class _FakeProxy:
    def snapshot(self):
        return {
            "p1": {
                "state": "open",
                "failures": 5,
                "opened_until": 9999999999.0,
                "last_error": "HTTP 503",
                "last_failure_at": 9999999990.0,
            }
        }


def test_health_is_down_when_only_provider_circuit_is_open(monkeypatch):
    cfg = GatewayConfig(
        providers={
            "p1": ProviderConfig(
                base_url="http://upstream.example",
                auth=AuthConfig(type="none"),
                passthrough=True,
                endpoints={"generate": EndpointConfig(path="/v1/generate")},
            )
        }
    )
    main.runtime_state.apply_config(cfg)
    monkeypatch.setattr(main, "proxy", _FakeProxy())

    payload, status_code = main._health_payload()

    assert status_code == 503
    assert payload["status"] == "down"
    assert payload["providers"]["p1"]["mode"] == "circuit_open"
