"""Gunicorn 生产配置：UvicornWorker 承载 FastAPI 异步应用，多进程支持高并发。

关键参数均可通过环境变量覆盖，方便在不同规格的容器/机器上调优，无需改代码重新构建镜像。
"""
import multiprocessing
import os


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# ---- 绑定地址 ----
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# ---- Worker 数量 ----
# 经验公式：CPU*2+1；同步 I/O 网关以 CPU 核数 * 2 为上限即可，过多进程反而增加调度开销
_cpu_count = multiprocessing.cpu_count()
workers = _int_env("GUNICORN_WORKERS", min(_cpu_count * 2 + 1, 9))

# ---- Worker 类型：uvicorn 的 ASGI worker，兼容 FastAPI 异步路由 ----
worker_class = "uvicorn.workers.UvicornWorker"

# ---- 每个 worker 内的并发连接数上限（uvicorn worker 通过事件循环并发处理） ----
worker_connections = _int_env("GUNICORN_WORKER_CONNECTIONS", 1000)

# ---- 超时控制 ----
# 下游 Provider 请求最长 120s（见 config/gateway.yaml endpoints.timeout），worker timeout 需大于业务超时
timeout = _int_env("GUNICORN_TIMEOUT", 150)
graceful_timeout = _int_env("GUNICORN_GRACEFUL_TIMEOUT", 30)
keepalive = _int_env("GUNICORN_KEEPALIVE", 5)

# ---- 防止内存泄漏累积：worker 处理一定请求数后自动重启 ----
max_requests = _int_env("GUNICORN_MAX_REQUESTS", 2000)
max_requests_jitter = _int_env("GUNICORN_MAX_REQUESTS_JITTER", 200)

# ---- 预加载应用：fork 前先 import，加快 worker 启动、节省内存（多进程共享只读内存页） ----
preload_app = os.getenv("GUNICORN_PRELOAD", "true").lower() == "true"

# ---- 日志：容器场景直接输出到 stdout/stderr，交给容器运行时/日志采集系统处理 ----
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = (
    '%(h)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sus'
)

# ---- 进程命名，方便 ps/top 排查 ----
proc_name = "sync-gateway"
