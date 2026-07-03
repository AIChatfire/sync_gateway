"""下游代理韧性测试"""
import asyncio

import httpx
import pytest

from app.core.config import ResilienceConfig
from app.services.proxy import CircuitOpenError, ProxyClient


def test_proxy_opens_circuit_after_repeated_5xx():
    async def scenario():
        proxy = ProxyClient()
        await proxy.client.aclose()
        proxy.client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(503))
        )
        resilience = ResilienceConfig(
            max_concurrency=2,
            failure_threshold=2,
            recovery_seconds=30,
            retry_attempts=0,
        )

        try:
            first = await proxy.request(
                provider_name="p1",
                resilience=resilience,
                method="POST",
                url="http://upstream.example/v1/generate",
                headers={},
                json_body={"prompt": "cat"},
                timeout=1,
            )
            second = await proxy.request(
                provider_name="p1",
                resilience=resilience,
                method="POST",
                url="http://upstream.example/v1/generate",
                headers={},
                json_body={"prompt": "cat"},
                timeout=1,
            )

            assert first.status_code == 503
            assert second.status_code == 503
            with pytest.raises(CircuitOpenError):
                await proxy.request(
                    provider_name="p1",
                    resilience=resilience,
                    method="POST",
                    url="http://upstream.example/v1/generate",
                    headers={},
                    json_body={"prompt": "cat"},
                    timeout=1,
                )
        finally:
            await proxy.client.aclose()

    asyncio.run(scenario())
