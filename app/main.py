"""同步任务映射网关入口"""
import os
import copy
from contextlib import asynccontextmanager
from typing import Dict, Mapping, Optional
from fastapi import FastAPI, Request, Header, HTTPException, Query
from fastapi.responses import JSONResponse
import uvicorn

from app.core.config import GatewayConfig, AuthConfig, EndpointConfig
from app.core.observability import setup_logfire
from app.core.state import GatewayRuntimeState
from app.services.proxy import ProxyClient
from app.services.nacos import NacosConfigManager

# 运行时状态
runtime_state = GatewayRuntimeState()
config_manager: Optional[NacosConfigManager] = None
proxy: Optional[ProxyClient] = None


def _get_header_value(
    headers: Mapping[str, str],
    *names: Optional[str],
) -> Optional[str]:
    """按候选 header 名读取入口请求 credential，兼容大小写。"""
    seen = set()
    for name in names:
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        value = headers.get(name)
        if value:
            return value
    return None


def _build_auth_headers(auth: AuthConfig, request_headers: Mapping[str, str]) -> Dict[str, str]:
    """从入口请求 headers 构造下游鉴权头，不再从服务端环境变量读取 API key。"""
    if auth.type == "none":
        return {}

    if auth.type == "bearer":
        authorization = _get_header_value(request_headers, "Authorization")
        if authorization:
            return {"Authorization": authorization}

        api_key = _get_header_value(
            request_headers,
            auth.header_name,
            "X-API-Key",
            "X-Api-Key",
            "Api-Key",
            "API_KEY",
        )
        if api_key:
            return {"Authorization": f"Bearer {api_key}"}
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization or X-API-Key header",
        )

    if auth.type == "api_key":
        downstream_header = auth.header_name or "X-API-Key"
        api_key = _get_header_value(
            request_headers,
            downstream_header,
            "X-API-Key",
            "X-Api-Key",
            "Api-Key",
            "API_KEY",
        )
        if api_key:
            return {downstream_header: api_key}
        raise HTTPException(
            status_code=401,
            detail=f"Missing {downstream_header} header",
        )

    raise HTTPException(status_code=500, detail=f"Unsupported auth type: {auth.type}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时加载配置"""
    global config_manager, proxy
    proxy = ProxyClient()
    config_manager = NacosConfigManager(
        server_addresses=os.getenv("NACOS_SERVER"),
        data_id=os.getenv("NACOS_DATA_ID", "sync-gateway.yaml"),
        local_fallback="./config/gateway.yaml",
    )
    config_manager.add_listener(_on_config_change)
    config_manager.add_error_listener(_on_config_error)
    config_manager.start()
    yield
    if proxy:
        await proxy.client.aclose()


app = FastAPI(title="Sync Gateway", version="1.0.0", lifespan=lifespan)
setup_logfire(app)


def _on_config_change(cfg: GatewayConfig):
    errors = runtime_state.apply_config(cfg)
    print(
        f"[Config] loaded version={cfg.version}, "
        f"providers={list(cfg.providers.keys())}, provider_errors={list(errors.keys())}"
    )


def _on_config_error(error: Exception, raw: str):
    runtime_state.record_config_error(error)
    print(f"[Gateway] config error: {error}")


def resolve_endpoint_name(cfg: GatewayConfig, request_path: str) -> Optional[str]:
    """将客户端请求路径解析为逻辑端点名。

    /v1/generate 是显式兼容入口；动态通配路径只接受 routes 表中配置的路径。
    """
    return cfg.routes.get(request_path)


async def _dispatch(
    request: Request,
    endpoint_name: str,
    x_provider: Optional[str],
):
    """通用请求转发：请求转换 → 下游调用 → 响应转换

    endpoint_name 决定去 provider.endpoints 里取哪一条目标路径配置，
    从而实现「同一个来源路径，不同 provider 可转发到不同目标路径」。
    """
    snapshot = runtime_state.snapshot()
    cfg = snapshot.config
    if not cfg or not cfg.active or not proxy:
        raise HTTPException(status_code=503, detail="Gateway not ready")

    body = await request.json()
    provider_name = x_provider or body.get("provider")
    if not provider_name:
        raise HTTPException(status_code=400, detail="Missing X-Provider header")

    provider = cfg.providers.get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_name}")

    if provider_name in snapshot.provider_errors:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Provider {provider_name} unavailable: "
                f"{snapshot.provider_errors[provider_name]}"
            ),
        )

    engine = snapshot.transformers.get(provider_name)
    if not engine:
        raise HTTPException(status_code=503, detail=f"Provider {provider_name} unavailable")

    endpoint = provider.endpoints.get(endpoint_name)
    if not endpoint:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Provider {provider_name} has no endpoint "
                f"'{endpoint_name}' for path {request.url.path}"
            ),
        )

    # 1. 请求转换
    try:
        downstream_body = engine.transform_request(copy.deepcopy(body))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Request transform error: {e}")

    # 2. 鉴权头
    headers = {"Content-Type": "application/json"}
    headers.update(_build_auth_headers(provider.auth, request.headers))

    # 3. 下游调用（同步阻塞）
    url = provider.base_url.rstrip("/") + endpoint.path
    try:
        resp = await proxy.request(
            provider_name=provider_name,
            resilience=provider.resilience,
            method=endpoint.method,
            url=url,
            headers=headers,
            json_body=downstream_body,
            timeout=endpoint.timeout,
        )
        resp.raise_for_status()
        raw_resp = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}")

    # 4. 响应转换
    try:
        result = engine.transform_response(raw_resp)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Response transform error: {e}")

    return JSONResponse(content=result)


@app.post("/v1/generate")
async def generate(
    request: Request,
    x_provider: Optional[str] = Header(None),
):
    """兼容旧入口：固定走 "generate" 逻辑端点"""
    return await _dispatch(request, "generate", x_provider)


@app.get("/health")
async def health():
    """兼容健康检查：展示配置、Provider 与熔断状态。"""
    payload, status_code = _health_payload()
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/live")
async def live():
    """存活探针：进程可响应即可。"""
    return {"status": "alive"}


@app.get("/ready")
async def ready():
    """就绪探针：至少一个 Provider 可用才接流量。"""
    payload, status_code = _health_payload()
    return JSONResponse(status_code=status_code, content=payload)


def _health_payload():
    """构建健康响应；down/not_ready/inactive 返回 503，degraded 仍可接流量。"""
    snapshot = runtime_state.snapshot()
    if not snapshot.config:
        return (
            {
                "status": "not_ready",
                "last_config_error": snapshot.last_config_error,
            },
            503,
        )

    cfg = snapshot.config
    circuit_status = proxy.snapshot() if proxy else {}

    providers_status = {}
    for name, provider in cfg.providers.items():
        mode = "passthrough" if provider.passthrough else "transform"
        provider_error = snapshot.provider_errors.get(name)
        circuit = circuit_status.get(name, {"state": "closed", "failures": 0})
        circuit_open = circuit.get("state") == "open"
        if provider_error:
            mode = "error"
        elif circuit_open:
            mode = "circuit_open"
        generate_endpoint = provider.endpoints.get("generate", EndpointConfig(path="/"))
        providers_status[name] = {
            "status": "error" if provider_error or circuit_open else "ok",
            "error": provider_error,
            "mode": mode,
            "timeout": generate_endpoint.timeout,
            "max_concurrency": provider.resilience.max_concurrency,
            "circuit": circuit,
        }

    if not cfg.active:
        overall = "inactive"
    elif not providers_status:
        overall = "down"
    elif all(p["status"] == "ok" for p in providers_status.values()):
        overall = "ok"
    elif any(p["status"] == "ok" for p in providers_status.values()):
        overall = "degraded"
    else:
        overall = "down"

    status_code = 200 if overall in {"ok", "degraded"} else 503
    return {
        "status": overall,
        "version": cfg.version,
        "loaded_at": snapshot.loaded_at,
        "last_config_error": snapshot.last_config_error,
        "providers": providers_status,
    }, status_code


@app.get("/admin/history")
async def admin_history():
    """查看配置历史"""
    if not config_manager:
        raise HTTPException(status_code=503, detail="Config manager not ready")
    snapshot = runtime_state.snapshot()
    return {
        "current": snapshot.config.version if snapshot.config else None,
        "history": config_manager.history(),
    }


@app.post("/admin/rollback")
async def admin_rollback(steps: int = Query(1, ge=1)):
    """手动回退配置版本"""
    if not config_manager:
        raise HTTPException(status_code=503, detail="Config manager not ready")
    cfg = config_manager.rollback(steps)
    if not cfg:
        raise HTTPException(status_code=400, detail="Rollback failed: no history")
    return {"message": "Rollback success", "version": cfg.version}


# ---------------------------------------------------------------------------
# 动态路由通配入口：必须注册在所有具体路由（/v1/generate、/health、/admin/*）
# 之后 —— FastAPI/Starlette 按注册顺序匹配路由，通配路径放前面会吞掉后面的具体路由。
# ---------------------------------------------------------------------------
@app.post("/{full_path:path}")
async def dynamic_route(
    full_path: str,
    request: Request,
    x_provider: Optional[str] = Header(None),
):
    """动态路由入口：按 routes 配置将来源路径解析为逻辑端点名再转发。

    短格式示例（自动映射到默认 generate 端点）：
      routes:
        - "/v1/images/generations"
    Provider 可用 endpoint.path 短写下游源路径；多端点时仍支持完整 endpoints 映射。
    """
    snapshot = runtime_state.snapshot()
    if not snapshot.config:
        raise HTTPException(status_code=503, detail="Gateway not ready")

    request_path = "/" + full_path
    endpoint_name = resolve_endpoint_name(snapshot.config, request_path)
    if not endpoint_name:
        raise HTTPException(
            status_code=404,
            detail=f"No route configured for path: {request_path}",
        )

    return await _dispatch(request, endpoint_name, x_provider)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
