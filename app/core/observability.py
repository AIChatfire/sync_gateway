"""可观测性：基于 Logfire 的日志/追踪接入。

设计原则：
- 本地开发默认不上报（未设置 LOGFIRE_TOKEN 时 send_to_logfire='if-token-present' 会静默跳过网络发送）
- 生产环境只需注入 LOGFIRE_TOKEN 环境变量即可自动开启上报，无需改代码
- /health、/live、/ready 属于高频探活请求，默认从追踪中排除，避免噪音
"""
import os

import logfire


def setup_logfire(app) -> None:
    """初始化 Logfire：配置 + FastAPI/HTTPX 自动埋点。

    需在创建 FastAPI app 之后、注册路由之前调用一次。
    """
    logfire.instrument_system_metrics()
    logfire.configure(
        service_name=os.getenv("LOGFIRE_SERVICE_NAME", "sync-gateway"),
        environment=os.getenv("LOGFIRE_ENVIRONMENT", "development"),
        send_to_logfire="if-token-present",
        console=(
            logfire.ConsoleOptions(min_log_level="warn")
            if os.getenv("LOGFIRE_CONSOLE", "false").lower() != "true"
            else True
        ),
    )

    logfire.instrument_fastapi(
        app,
        excluded_urls=os.getenv("LOGFIRE_EXCLUDED_URLS", "/health|/live|/ready"),
        capture_headers=os.getenv("LOGFIRE_CAPTURE_HEADERS", "false").lower() == "true",
    )
    logfire.instrument_httpx(
        capture_headers=os.getenv("LOGFIRE_CAPTURE_HEADERS", "false").lower() == "true"
    )
