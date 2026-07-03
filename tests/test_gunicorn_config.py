"""Gunicorn 配置默认值与环境变量覆盖测试"""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4


CONFIG_PATH = Path(__file__).resolve().parents[1] / "deploy" / "gunicorn.conf.py"


def _load_config(monkeypatch, **env):
    for key in list(os.environ):
        if key.startswith("GUNICORN_"):
            monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))

    module_name = f"gunicorn_conf_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gunicorn_defaults_are_ha_oriented(monkeypatch):
    cfg = _load_config(monkeypatch)

    assert cfg.workers >= 2
    assert cfg.backlog == 2048
    assert cfg.timeout == 150
    assert cfg.graceful_timeout == cfg.timeout
    assert cfg.max_requests == 2000
    assert cfg.max_requests_jitter == 200
    assert cfg.capture_output is True
    assert cfg.forwarded_allow_ips == "*"
    assert cfg.limit_request_fields == 100
    assert cfg.statsd_host is None


def test_gunicorn_env_overrides(monkeypatch):
    cfg = _load_config(
        monkeypatch,
        GUNICORN_WORKERS=1,
        GUNICORN_BACKLOG=4096,
        GUNICORN_TIMEOUT=120,
        GUNICORN_GRACEFUL_TIMEOUT=180,
        GUNICORN_CAPTURE_OUTPUT="false",
        GUNICORN_WORKER_TMP_DIR="/tmp",
        GUNICORN_FORWARDED_ALLOW_IPS="10.0.0.1",
        GUNICORN_STATSD_HOST="127.0.0.1:8125",
    )

    assert cfg.workers == 1
    assert cfg.backlog == 4096
    assert cfg.timeout == 120
    assert cfg.graceful_timeout == 180
    assert cfg.capture_output is False
    assert cfg.worker_tmp_dir == "/tmp"
    assert cfg.forwarded_allow_ips == "10.0.0.1"
    assert cfg.statsd_host == "127.0.0.1:8125"
