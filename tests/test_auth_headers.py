"""入口 header 鉴权构造测试"""
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app import main
from app.core.config import AuthConfig, EndpointConfig, GatewayConfig, ProviderConfig


def test_bearer_auth_prefers_request_authorization_header(monkeypatch):
    monkeypatch.setenv("VOLC_SD_API_KEY", "server-secret")

    result = main._build_auth_headers(
        AuthConfig(type="bearer", env="VOLC_SD_API_KEY"),
        Headers({"Authorization": "Bearer request-secret"}),
    )

    assert result == {"Authorization": "Bearer request-secret"}


def test_bearer_auth_uses_request_x_api_key_header(monkeypatch):
    monkeypatch.setenv("VOLC_SD_API_KEY", "server-secret")

    result = main._build_auth_headers(
        AuthConfig(type="bearer", env="VOLC_SD_API_KEY"),
        Headers({"X-API-Key": "request-secret"}),
    )

    assert result == {"Authorization": "Bearer request-secret"}


def test_bearer_auth_uses_request_api_key_header_name():
    result = main._build_auth_headers(
        AuthConfig(type="bearer"),
        Headers({"API_KEY": "request-secret"}),
    )

    assert result == {"Authorization": "Bearer request-secret"}


def test_api_key_auth_uses_configured_request_header(monkeypatch):
    monkeypatch.setenv("VENDOR_API_KEY", "server-secret")

    result = main._build_auth_headers(
        AuthConfig(type="api_key", env="VENDOR_API_KEY", header_name="X-Vendor-Key"),
        Headers({"X-Vendor-Key": "request-secret"}),
    )

    assert result == {"X-Vendor-Key": "request-secret"}


def test_auth_missing_request_header_does_not_fall_back_to_env(monkeypatch):
    monkeypatch.setenv("VOLC_SD_API_KEY", "server-secret")

    with pytest.raises(HTTPException) as exc_info:
        main._build_auth_headers(
            AuthConfig(type="bearer", env="VOLC_SD_API_KEY"),
            Headers({}),
        )

    assert exc_info.value.status_code == 401


class _FakeClient:
    async def aclose(self):
        return None


class _CapturingProxy:
    def __init__(self):
        self.client = _FakeClient()
        self.calls = []

    def snapshot(self):
        return {}

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        request = httpx.Request(kwargs["method"], kwargs["url"])
        return httpx.Response(200, json={"ok": True}, request=request)


def test_generate_forwards_api_key_from_request_header(monkeypatch):
    cfg = GatewayConfig(
        providers={
            "p1": ProviderConfig(
                base_url="http://upstream.example",
                auth=AuthConfig(type="bearer", env="UPSTREAM_API_KEY"),
                passthrough=True,
                endpoints={"generate": EndpointConfig(path="/v1/generate")},
            )
        }
    )

    with TestClient(main.app) as client:
        main.runtime_state.apply_config(cfg)
        proxy = _CapturingProxy()
        monkeypatch.setattr(main, "proxy", proxy)

        response = client.post(
            "/v1/generate",
            headers={"X-Provider": "p1", "X-API-Key": "request-secret"},
            json={"prompt": "cat"},
        )

    assert response.status_code == 200
    assert proxy.calls[0]["headers"]["Authorization"] == "Bearer request-secret"
