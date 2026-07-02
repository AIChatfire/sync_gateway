"""同步任务映射网关入口"""
import os
import copy
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

from core.config import GatewayConfig, ProviderConfig, AuthConfig
from core.engine import TransformEngine
from core.proxy import ProxyClient
from core.nacos import NacosConfigManager

app = FastAPI(title="Sync Gateway", version="1.0.0")
proxy = ProxyClient()

# 运行时状态
_current_config: Optional[GatewayConfig] = None
_transformers: Dict[str, TransformEngine] = {}
_errors: Dict[str, str] = {}


def _build_transformers(cfg: GatewayConfig):
    """构建所有 Provider 转换器，单个失败不影响其他"""
    global _transformers, _errors
    new_t: Dict[str, TransformEngine] = {}
    new_err: Dict[str, str] = {}
    for name, provider in cfg.providers.items():
        try:
            new_t[name] = TransformEngine(provider)
        except Exception as e:
            new_err[name] = str(e)
    _transformers = new_t
    _errors = new_err


def _get_auth_header(auth: AuthConfig) -> Dict[str, str]:
    if auth.type == "none":
        return {}
    token = os.getenv(auth.env) if auth.env else ""
    if auth.type == "bearer":
        return {"Authorization": f"Bearer {token}"}
    if auth.type == "api_key" and auth.header_name:
        return {auth.header_name: token}
    return {}


def _resolve_provider(request: Request, body: Dict[str, Any]) -> str:
    """解析目标 Provider：Header > Body.provider > Body.model 前缀"""
    provider = request.headers.get("X-Provider")
    if provider:
        return provider
    provider = body.get("provider")
    if provider:
        return provider
    model = body.get("model", "")
    if model:
        for name in _current_config.providers.keys() if _current_config else []:
            if model.startswith(name):
                return name
    raise HTTPException(status_code=400, detail="Missing X-Provider header or provider field")


@app.post("/v1/generate")
async def generate(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_provider: Optional[str] = Header(None),
):
    """同步生成入口：请求转换 → 下游调用 → 响应转换"""
    if not _current_config or not _current_config.active:
        raise HTTPException(status_code=503, detail="Gateway not ready")

    body = await request.json()
    provider_name = x_provider or body.get("provider")
    if not provider_name:
        raise HTTPException(status_code=400, detail="Missing X-Provider header")

    provider = _current_config.providers.get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_name}")

    if provider_name in _errors:
        raise HTTPException(
            status_code=503,
            detail=f"Provider {provider_name} unavailable: {_errors[provider_name]}",
        )

    engine = _transformers[provider_name]
    endpoint = provider.endpoints.get("generate")
    if not endpoint:
        raise HTTPException(status_code=500, detail=f"No generate endpoint for {provider_name}")

    # 1. 请求转换
    try:
        downstream_body = engine.transform_request(copy.deepcopy(body))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Request transform error: {e}")

    # 2. 鉴权头
    headers = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    else:
        headers.update(_get_auth_header(provider.auth))

    # 3. 下游调用（同步阻塞）
    url = provider.base_url.rstrip("/") + endpoint.path
    try:
        resp = await proxy.request(
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


@app.get("/health")
async def health():
    """健康检查：展示各 Provider 状态与模式"""
    if not _current_config:
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    providers_status = {}
    for name, provider in _current_config.providers.items():
        mode = "passthrough" if provider.passthrough else "transform"
        if name in _errors:
            mode = "error"
        providers_status[name] = {
            "status": "error" if name in _errors else "ok",
            "error": _errors.get(name),
            "mode": mode,
            "timeout": provider.endpoints.get("generate", {}).timeout if provider.endpoints.get("generate") else 120,
        }

    overall = "ok" if not _errors else "degraded" if any(
        p["status"] == "ok" for p in providers_status.values()
    ) else "down"

    return {
        "status": overall,
        "version": _current_config.version,
        "providers": providers_status,
    }


@app.get("/admin/history")
async def admin_history():
    """查看配置历史"""
    if not config_manager:
        raise HTTPException(status_code=503, detail="Config manager not ready")
    return {"current": _current_config.version if _current_config else None, "history": config_manager.history()}


@app.post("/admin/rollback")
async def admin_rollback(steps: int = Query(1, ge=1)):
    """手动回退配置版本"""
    if not config_manager:
        raise HTTPException(status_code=503, detail="Config manager not ready")
    cfg = config_manager.rollback(steps)
    if not cfg:
        raise HTTPException(status_code=400, detail="Rollback failed: no history")
    _build_transformers(cfg)
    return {"message": "Rollback success", "version": cfg.version}


# ========== 启动 ==========
config_manager: Optional[NacosConfigManager] = None


def on_config_change(cfg: GatewayConfig):
    global _current_config
    _current_config = cfg
    _build_transformers(cfg)
    print(f"[Config] loaded version={cfg.version}, providers={list(cfg.providers.keys())}")


def on_config_error(error: Exception, raw: str):
    print(f"[Gateway] config error: {error}")


@app.on_event("startup")
async def startup():
    global config_manager
    config_manager = NacosConfigManager(
        server_addresses=os.getenv("NACOS_SERVER"),
        data_id=os.getenv("NACOS_DATA_ID", "sync-gateway.yaml"),
        local_fallback="./gateway.yaml",
    )
    config_manager.add_listener(on_config_change)
    config_manager.add_error_listener(on_config_error)
    cfg = config_manager.start()
    on_config_change(cfg)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
