# syntax=docker/dockerfile:1
# ---------- Stage 1: builder ----------
FROM python:3.12-slim AS builder

WORKDIR /build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 用独立虚拟环境隔离依赖，运行阶段整体拷贝，不依赖 --user/HOME 语义，避免非 root 用户下 site-packages 路径失配
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

RUN pip install gunicorn

COPY requirements.txt .
RUN pip install -r requirements.txt

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

# 非 root 运行用户
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app

# 拷贝已构建好的虚拟环境（含 gunicorn + 全部依赖）
COPY --from=builder /opt/venv /opt/venv

# 拷贝应用代码与默认配置
COPY app ./app
COPY config ./config
COPY deploy/gunicorn.conf.py ./deploy/gunicorn.conf.py

RUN chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).status==200 else 1)"

# gunicorn + uvicorn worker：多进程横向扩展，配合 app 内部 asyncio 支持高并发 I/O
CMD ["gunicorn", "app.main:app", "-c", "deploy/gunicorn.conf.py"]
