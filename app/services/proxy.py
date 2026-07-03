"""HTTP 透传客户端 + Provider 级韧性保护。"""
import asyncio
import os
import time
from dataclasses import dataclass
from threading import RLock
from typing import Dict, Any, Optional

import httpx

from app.core.config import ResilienceConfig


def _int_env(name: str, default: int) -> int:
    try:
        value = os.getenv(name)
        return int(value) if value else default
    except (TypeError, ValueError):
        return default


class CircuitOpenError(RuntimeError):
    """Provider 熔断打开时拒绝新的下游请求。"""


@dataclass
class _CircuitState:
    failures: int = 0
    opened_until: float = 0.0
    last_error: Optional[str] = None
    last_failure_at: Optional[float] = None


class ProxyClient:
    def __init__(self):
        self.client = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(
                max_connections=_int_env("PROXY_MAX_CONNECTIONS", 100),
                max_keepalive_connections=_int_env("PROXY_MAX_KEEPALIVE_CONNECTIONS", 20),
            ),
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
        )
        self._lock = RLock()
        self._circuits: Dict[str, _CircuitState] = {}
        self._semaphores: Dict[str, tuple[int, asyncio.Semaphore]] = {}

    def _get_semaphore(self, provider_name: str, max_concurrency: int) -> asyncio.Semaphore:
        with self._lock:
            current = self._semaphores.get(provider_name)
            if current and current[0] == max_concurrency:
                return current[1]

            semaphore = asyncio.Semaphore(max_concurrency)
            self._semaphores[provider_name] = (max_concurrency, semaphore)
            return semaphore

    def _get_circuit(self, provider_name: str) -> _CircuitState:
        with self._lock:
            return self._circuits.setdefault(provider_name, _CircuitState())

    def _ensure_circuit_allows_request(self, provider_name: str) -> None:
        state = self._get_circuit(provider_name)
        if state.opened_until > time.time():
            remaining = round(state.opened_until - time.time(), 2)
            raise CircuitOpenError(f"Provider {provider_name} circuit open for {remaining}s")

    def _record_success(self, provider_name: str) -> None:
        with self._lock:
            state = self._circuits.setdefault(provider_name, _CircuitState())
            state.failures = 0
            state.opened_until = 0.0
            state.last_error = None
            state.last_failure_at = None

    def _record_failure(
        self,
        provider_name: str,
        error: str,
        resilience: ResilienceConfig,
    ) -> None:
        with self._lock:
            state = self._circuits.setdefault(provider_name, _CircuitState())
            state.failures += 1
            state.last_error = error
            state.last_failure_at = time.time()
            if state.failures >= resilience.failure_threshold:
                state.opened_until = time.time() + resilience.recovery_seconds

    async def _sleep_before_retry(self, attempt: int, resilience: ResilienceConfig) -> None:
        if resilience.retry_backoff_seconds <= 0:
            return
        await asyncio.sleep(resilience.retry_backoff_seconds * (2 ** attempt))

    @staticmethod
    def _is_retryable_exception(exc: Exception) -> bool:
        return isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.PoolTimeout,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
            ),
        )

    async def request(
        self,
        provider_name: str,
        resilience: ResilienceConfig,
        method: str,
        url: str,
        headers: Dict[str, str],
        json_body: Dict[str, Any],
        timeout: float,
    ) -> httpx.Response:
        self._ensure_circuit_allows_request(provider_name)
        semaphore = self._get_semaphore(provider_name, resilience.max_concurrency)

        async with semaphore:
            attempts = resilience.retry_attempts + 1
            for attempt in range(attempts):
                try:
                    response = await self.client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        json=json_body,
                        timeout=timeout,
                    )
                    if (
                        response.status_code in resilience.retry_on_status
                        and attempt < resilience.retry_attempts
                    ):
                        await self._sleep_before_retry(attempt, resilience)
                        continue

                    if response.status_code >= 500:
                        self._record_failure(
                            provider_name,
                            f"HTTP {response.status_code}",
                            resilience,
                        )
                    else:
                        self._record_success(provider_name)
                    return response
                except Exception as exc:
                    if (
                        self._is_retryable_exception(exc)
                        and attempt < resilience.retry_attempts
                    ):
                        await self._sleep_before_retry(attempt, resilience)
                        continue
                    self._record_failure(provider_name, str(exc), resilience)
                    raise

        raise RuntimeError("unreachable proxy retry state")

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        with self._lock:
            return {
                name: {
                    "state": "open" if state.opened_until > now else "closed",
                    "failures": state.failures,
                    "opened_until": state.opened_until or None,
                    "last_error": state.last_error,
                    "last_failure_at": state.last_failure_at,
                }
                for name, state in self._circuits.items()
            }
