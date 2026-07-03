"""Gunicorn 生产配置：UvicornWorker 承载 FastAPI 异步应用，多进程支持高并发。

关键参数均可通过环境变量覆盖，方便在不同规格的容器/机器上调优，无需改代码重新构建镜像。
"""
import multiprocessing
import os


def _int_env(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        raw = os.getenv(name)
        value = int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        value = default

    if minimum is not None:
        value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.lower() in {"1", "true", "yes", "y", "on"}


def _optional_env(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw


# ---- 绑定地址 ----
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
backlog = _int_env("GUNICORN_BACKLOG", 2048, minimum=64)

# ---- Worker 数量 ----
# 经验公式：CPU*2+1；默认至少 2 个 worker，避免单 worker 卡死时整实例完全不可服务
_cpu_count = multiprocessing.cpu_count()
_max_default_workers = _int_env("GUNICORN_MAX_DEFAULT_WORKERS", 9, minimum=1)
_default_workers = min(max(_cpu_count * 2 + 1, 2), _max_default_workers)
workers = _int_env("GUNICORN_WORKERS", _default_workers, minimum=1)

# ---- Worker 类型：uvicorn 的 ASGI worker，兼容 FastAPI 异步路由 ----
worker_class = "uvicorn.workers.UvicornWorker"

# ---- 每个 worker 内的并发连接数上限（uvicorn worker 通过事件循环并发处理） ----
worker_connections = _int_env("GUNICORN_WORKER_CONNECTIONS", 1000, minimum=1)

# ---- 超时控制 ----
# 下游 Provider 请求最长 120s（见 config/gateway.yaml endpoints.timeout），worker timeout 需大于业务超时。
# graceful_timeout 默认与 timeout 一致，给滚动发布/重启中的长请求足够收尾时间。
timeout = _int_env("GUNICORN_TIMEOUT", 150, minimum=1)
graceful_timeout = _int_env("GUNICORN_GRACEFUL_TIMEOUT", timeout, minimum=1)
keepalive = _int_env("GUNICORN_KEEPALIVE", 5, minimum=1)

# ---- 防止内存泄漏累积：worker 处理一定请求数后自动重启 ----
max_requests = _int_env("GUNICORN_MAX_REQUESTS", 2000, minimum=0)
max_requests_jitter = _int_env("GUNICORN_MAX_REQUESTS_JITTER", 200, minimum=0)

# ---- 预加载应用：fork 前先 import，加快 worker 启动、节省内存（多进程共享只读内存页）----
# app 的网络客户端在 FastAPI lifespan 中创建，避免 preload 后跨进程共享连接。
preload_app = _bool_env("GUNICORN_PRELOAD", True)

# ---- Docker/K8s 环境下把 worker 心跳临时文件放到内存盘，降低磁盘阻塞导致的误杀概率 ----
_default_worker_tmp = "/dev/shm" if os.path.isdir("/dev/shm") else None
worker_tmp_dir = _optional_env("GUNICORN_WORKER_TMP_DIR", _default_worker_tmp)

# ---- 反向代理/LB 兼容 ----
# 容器通常在可信 LB/Nginx 后面运行；如直接暴露公网，请显式收紧为代理 IP/CIDR。
forwarded_allow_ips = os.getenv("GUNICORN_FORWARDED_ALLOW_IPS", "*")
secure_scheme_headers = {
    "X-FORWARDED-PROTO": "https",
    "X-FORWARDED-SSL": "on",
}

# ---- 请求头限制：保留 Gunicorn 默认量级，同时允许按生产流量调优 ----
limit_request_line = _int_env("GUNICORN_LIMIT_REQUEST_LINE", 8190, minimum=0)
limit_request_fields = _int_env("GUNICORN_LIMIT_REQUEST_FIELDS", 100, minimum=1)
limit_request_field_size = _int_env(
    "GUNICORN_LIMIT_REQUEST_FIELD_SIZE",
    8190,
    minimum=0,
)

# ---- 日志：容器场景直接输出到 stdout/stderr，交给容器运行时/日志采集系统处理 ----
accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
capture_output = _bool_env("GUNICORN_CAPTURE_OUTPUT", True)
access_log_format = (
    '%(h)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sus '
    'xff="%({x-forwarded-for}i)s" request_id="%({x-request-id}i)s"'
)

# ---- 可选 Gunicorn 级指标：配置 host:port 后输出 worker/request 指标到 StatsD ----
statsd_host = _optional_env("GUNICORN_STATSD_HOST")
statsd_prefix = os.getenv("GUNICORN_STATSD_PREFIX", "sync_gateway")
dogstatsd_tags = os.getenv("GUNICORN_DOGSTATSD_TAGS", "")

# ---- 进程命名，方便 ps/top 排查 ----
proc_name = os.getenv("GUNICORN_PROC_NAME", "sync-gateway")


def when_ready(server):
    server.log.info(
        "Gunicorn ready: workers=%s worker_class=%s timeout=%ss graceful_timeout=%ss",
        workers,
        worker_class,
        timeout,
        graceful_timeout,
    )


def worker_abort(worker):
    worker.log.warning("Worker aborted: pid=%s", worker.pid)
