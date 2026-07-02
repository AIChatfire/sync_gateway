"""HTTP 透传客户端"""
import httpx
from typing import Dict, Any


class ProxyClient:
    def __init__(self):
        self.client = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
        )

    async def request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        json_body: Dict[str, Any],
        timeout: float,
    ) -> httpx.Response:
        return await self.client.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body,
            timeout=timeout,
        )
