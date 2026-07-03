# Sync Gateway — 同步任务映射服务

基于同样的四模态架构（透传/声明式/表达式/脚本），专为同步阻塞任务（文生图、短文本生成等）设计。

## 特性

- **四模态转换**：透传(passthrough) / 声明式(request_map) / 表达式(expr) / 脚本(script)
- **Nacos 热更新**：配置推送秒级生效
- **快照回滚**：保留最近 5 个版本，支持 `/admin/rollback` 手动回退
- **错误隔离**：单个 Provider 脚本错误不影响其他 Provider
- **Provider 韧性保护**：按 Provider 配置并发上限、失败熔断和可选重试
- **健康检查**：`GET /live` 存活探针、`GET /ready` 就绪探针、`GET /health` 诊断详情

## 项目结构

```
sync_gateway/
├── app/                    # 应用代码
│   ├── main.py             # FastAPI 入口与路由
│   ├── api/                # API 路由层（按版本/资源拆分）
│   ├── core/               # 核心领域：配置契约、转换引擎
│   │   ├── config.py
│   │   └── engine.py
│   └── services/           # 基础设施服务：代理、配置管理
│       ├── proxy.py
│       └── nacos.py
├── config/                 # 配置文件
│   └── gateway.yaml        # Provider 映射配置
├── deploy/                 # 部署相关配置
│   └── gunicorn.conf.py    # Gunicorn 生产配置（worker 数、超时等）
├── tests/                  # 测试
├── scripts/                # 运维/初始化脚本
├── docs/                   # 文档
├── Dockerfile              # 多阶段构建镜像
├── docker-compose.yml      # 容器化部署编排
├── .env.example            # 环境变量示例
├── requirements.txt
└── README.md
```

## 快速启动

```bash
# 1. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动服务（从项目根目录运行）
python -m app.main
```

## Docker 部署（生产 / 高并发）

生产环境使用 `gunicorn + uvicorn worker` 多进程模式，替代开发用的 `python -m app.main` 单进程模式，充分利用多核 CPU 并发处理请求。

### 快速启动

```bash
# 1. 复制并按需修改环境变量
cp .env.example .env

# 2. 构建镜像并启动（默认 worker 数 = CPU*2+1，最多 9 个，至少 2 个）
docker compose up -d --build

# 3. 查看日志
docker compose logs -f sync-gateway

# 4. 就绪检查
curl http://localhost:8000/ready
```

### 手动 docker 命令（不依赖 compose）

```bash
docker build -t sync-gateway:latest .

docker run -d --name sync-gateway \
  -p 8000:8000 \
  -e NACOS_SERVER=http://nacos:8848 \
  -e VOLC_SD_BASE_URL=https://xxx \
  -v $(pwd)/config/gateway.yaml:/app/config/gateway.yaml:ro \
  sync-gateway:latest
```

### 并发调优参数（`deploy/gunicorn.conf.py`，均可用环境变量覆盖）

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `GUNICORN_WORKERS` | `CPU*2+1`（默认上限 9，至少 2） | 进程数，每个进程独立事件循环，横向扩展并发能力；显式设置时不受默认上限限制 |
| `GUNICORN_MAX_DEFAULT_WORKERS` | 9 | 未显式设置 `GUNICORN_WORKERS` 时的默认 worker 上限 |
| `GUNICORN_WORKER_CONNECTIONS` | 1000 | 单个 worker 内的最大并发连接数（uvicorn 事件循环承载） |
| `GUNICORN_BACKLOG` | 2048 | master socket 排队长度，缓冲短时连接峰值 |
| `GUNICORN_TIMEOUT` | 150 | worker 超时（秒），需大于下游 Provider 最长超时（当前 120s） |
| `GUNICORN_GRACEFUL_TIMEOUT` | 150 | 优雅关闭等待时间；滚动发布时给长请求收尾，建议不小于业务 timeout |
| `GUNICORN_KEEPALIVE` | 5 | keep-alive 连接保持秒数，通常由前置 LB/Nginx 复用连接 |
| `GUNICORN_MAX_REQUESTS` | 2000 | 单 worker 处理请求数上限，超过后自动重启，防止内存泄漏累积 |
| `GUNICORN_MAX_REQUESTS_JITTER` | 200 | worker 回收随机抖动，避免所有 worker 同时重启 |
| `GUNICORN_PRELOAD` | true | 预加载应用后再 fork worker，减少启动时间与内存占用 |
| `GUNICORN_WORKER_TMP_DIR` | `/dev/shm` | worker 心跳临时目录，容器内默认使用内存盘降低磁盘阻塞误杀 |
| `GUNICORN_FORWARDED_ALLOW_IPS` | `*` | 信任反向代理传入的 forwarded headers；公网直连时应收紧为代理 IP/CIDR |
| `GUNICORN_LIMIT_REQUEST_LINE` | 8190 | 请求行长度上限 |
| `GUNICORN_LIMIT_REQUEST_FIELDS` | 100 | 请求 header 数量上限 |
| `GUNICORN_LIMIT_REQUEST_FIELD_SIZE` | 8190 | 单个请求 header 大小上限 |
| `GUNICORN_CAPTURE_OUTPUT` | true | 捕获 worker stdout/stderr 到 Gunicorn error log，便于容器日志采集 |
| `GUNICORN_STATSD_HOST` | 空 | 可选 `host:port`，启用 Gunicorn 级 StatsD 指标 |

**容量估算参考**：单机 4 核场景下，`workers=9`、`worker_connections=1000`，理论最大并发连接数 ≈ 9000（实际吞吐取决于下游 Provider 响应速度，同步生成类接口通常是 I/O 瓶颈而非 CPU 瓶颈）。如需进一步扩容，优先水平扩展多个容器实例 + 前置负载均衡（Nginx/云 LB），而非无限堆高单机 worker 数。

### 高可用建议

- **多实例 + 负载均衡**：`docker compose up -d --scale sync-gateway=3` 或用 K8s Deployment 多副本，前面挂 Nginx/云 LB 做流量分发
- **配置热更新不依赖重启**：生产建议接入 Nacos（设置 `NACOS_SERVER`），配置变更秒级生效，无需重新部署容器
- **探针已内置**：Dockerfile 中 `HEALTHCHECK` 与 compose 中的 `healthcheck` 均探测 `/ready`；K8s 可用 `/live` 做 liveness、`/ready` 做 readiness
- **优雅下线**：compose 默认 `GATEWAY_STOP_GRACE_PERIOD=180s`，应大于 `GUNICORN_GRACEFUL_TIMEOUT`，避免滚动发布时硬杀长请求
- **Worker 分散回收**：`GUNICORN_MAX_REQUESTS_JITTER` 避免多个 worker 同时重启，降低瞬时容量塌陷风险
- **下游隔离**：每个 Provider 可独立设置 `resilience.max_concurrency`、`failure_threshold`、`recovery_seconds`、`retry_attempts`，一个坏下游不会拖垮整个网关

## 运行时架构

当前推荐继续采用**模块化单体网关 + 多实例水平扩展**，先把高可用边界做扎实，再按真实流量拆分。核心路径如下：

```text
Client / LB
    │
    ▼
FastAPI route layer
    │
    ▼
GatewayRuntimeState ── NacosConfigManager
    │
    ▼
TransformEngine per Provider
    │
    ▼
ProxyClient per-provider concurrency / circuit breaker
    │
    ▼
Downstream Provider
```

关键原则：

- **配置原子替换**：Nacos 或本地配置加载后，先构建所有 Provider 转换器，再一次性替换运行时快照；坏 Provider 进入降级状态，其他 Provider 继续服务
- **无状态服务实例**：请求态不落本地磁盘，适合多副本部署；配置历史只作为单实例回滚辅助，生产配置源仍以 Nacos/Git 为准
- **显式扩展点**：新增来源路径改 `routes`，新增下游能力改 `providers.<name>.endpoints`，新增隔离策略改 `resilience`
- **故障语义清晰**：`/live` 只代表进程活着，`/ready` 代表可接流量，`/health` 用于人工或监控诊断

## CI/CD

`.github/workflows/docker-image.yml` 定义了完整流水线，`test` 通过后才会 `build-and-push`：

```
push/PR → test（flake8 + pytest）→ build-and-push（仅 master/tag，PR 不推送）→ 推送到 GHCR
```

- **触发条件**：push 到 `master`、打 `v*.*.*` 标签、PR 到 `master`（PR 只跑测试，不构建推送）、也支持手动触发（Actions 页面 `Run workflow`）
- **镜像仓库**：GitHub Container Registry（`ghcr.io/<owner>/<repo>`），用仓库自带的 `GITHUB_TOKEN` 鉴权，无需额外配置 secret
- **镜像标签规则**：
  | 触发场景 | 生成标签 |
  |---|---|
  | push 到 `master` | `master`、`latest`、`<7位短commit sha>` |
  | 打标签 `v1.2.3` | `1.2.3`、`1.2`、`latest` |
  | 其他分支 push | `<分支名>` |
- **构建加速**：用 GitHub Actions 缓存（`type=gha`）复用 Docker 层，多阶段 Dockerfile 的依赖安装层命中缓存后可跳过重新 `pip install`

**首次使用前**：在仓库 `Settings → Actions → General → Workflow permissions` 里勾选 "Read and write permissions"，否则 `packages: write` 权限不足会导致推送失败。

**上线拉取镜像**（免本地构建）：
```bash
# .env 中设置 GATEWAY_IMAGE=ghcr.io/<owner>/sync_gateway:latest
docker compose pull && docker compose up -d
```

如需扩展为「push 后自动 SSH 到服务器部署」，在 `build-and-push` job 后追加一个 deploy job（用 `appleboy/ssh-action` 之类的 action），把服务器地址/账号/密钥配置到仓库 Secrets 即可，目前先保持"构建推送镜像、手动拉取上线"这一步，避免过早引入生产凭据风险。

## 可观测性（Logfire）

集成了 [Pydantic Logfire](https://logfire.pydantic.dev)，对 FastAPI 请求和 httpx 下游调用自动打点（`app/core/observability.py`），无需在业务代码里手写埋点。

- **默认零配置**：不设置 `LOGFIRE_TOKEN` 时不会联网上报，只在本机 console 打印 `warn` 及以上级别日志，本地开发不受影响
- **生产开启只需一步**：在 [logfire.pydantic.dev](https://logfire.pydantic.dev) 创建项目拿到写入令牌，填入 `.env` 的 `LOGFIRE_TOKEN` 后重启容器即可自动上报，不用改代码
- **追踪范围**：每个 `/v1/generate` 请求（含参数校验详情）+ 每次下游 httpx 调用（延迟、状态码），探针接口默认排除，避免噪音
- **相关环境变量**：

  | 环境变量 | 默认值 | 说明 |
  |---|---|---|
  | `LOGFIRE_TOKEN` | 空 | 写入令牌，留空则不上报 |
  | `LOGFIRE_SERVICE_NAME` | `sync-gateway` | Logfire 项目里的服务名 |
  | `LOGFIRE_ENVIRONMENT` | `production`（compose 默认）/ `development`（本地默认） | 区分环境的标签 |
  | `LOGFIRE_CAPTURE_HEADERS` | `false` | 是否记录请求/响应 headers（含 Authorization，谨慎开启） |
  | `LOGFIRE_EXCLUDED_URLS` | `/health|/live|/ready` | 排除追踪的 URL 正则 |

## 动态路由（入口路径列表）

单端点 Provider 推荐用短格式：`routes` 写入口路径列表，Provider 写 `endpoint.path` 作为下游源路径。

```yaml
routes:
  - "/v1/images/generations"
  - "/api/v3/images/generations"

providers:
  ark_seedream:
    base_url: "https://ark.cn-beijing.volces.com"
    auth: {type: bearer}
    passthrough: true
    endpoint:
      method: POST
      path: "/api/v3/images/generations"
      timeout: 180
```

效果：客户端请求 `POST /v1/images/generations` + `X-Provider: ark_seedream`，实际转发到 `https://ark.cn-beijing.volces.com/api/v3/images/generations`。

- **新增入口路径**：只需在 `routes` 列表里加一行，无需写 `generate`
- **旧格式仍兼容**：`routes: {"/path": "generate"}` 和 `endpoints.generate` 仍可继续使用
- **多端点场景**：如果同一 Provider 未来有 `upload/query/cancel` 等多个端点，再使用完整格式 `routes: {"/path": "endpoint_name"}` + `endpoints.<endpoint_name>`
- **兼容旧行为**：未在 `routes` 中配置的路径请求会返回 404；`/v1/generate` 固定走 `generate` 端点，作为历史兼容入口保留
- **实现位置**：`app/main.py` 的 `resolve_endpoint_name()` + 通配路由 `POST /{full_path:path}`（必须注册在所有具体路由之后，避免吞掉 `/admin/*` 等管理接口）

## 调用示例

下游 API key 从请求入口 headers 获取，不再通过服务端 `*_API_KEY` 环境变量注入。`auth.type: bearer` 的 Provider 支持两种入口写法：

- `Authorization: Bearer <api_key>`：原样转发给下游
- `X-API-Key: <api_key>` 或 `API_KEY: <api_key>`：网关转换为 `Authorization: Bearer <api_key>` 后转发

### 透传模式（火山接口）
```bash
curl -X POST http://localhost:8000/v1/generate \
  -H "Authorization: Bearer $VOLC_TOKEN" \
  -H "X-Provider: volc_sd" \
  -H "Content-Type: application/json" \
  -d '{"model":"sd-xl","prompt":"a cat","width":1024}'
```

### 转换模式（声明式+表达式）
```bash
curl -X POST http://localhost:8000/v1/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Provider: seedance" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a cat","quality":"hd","width":512}'
```

### 脚本模式（Kling）
```bash
curl -X POST http://localhost:8000/v1/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Provider: kling" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a cat","aspect_ratio":"9:16","n":4}'
```

## 运维接口

```bash
# 健康检查 / 探针
GET /health
GET /live
GET /ready

# 查看配置历史
GET /admin/history

# 回退到上一个版本
POST /admin/rollback?steps=1
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `NACOS_SERVER` | Nacos 地址，如 `http://nacos:8848` |
| `NACOS_DATA_ID` | 配置 ID，默认 `sync-gateway.yaml` |
| `CONFIG_MAX_HISTORY` | 最大历史版本数，默认 5 |
| `PROXY_MAX_CONNECTIONS` / `PROXY_MAX_KEEPALIVE_CONNECTIONS` | 下游 HTTP 全局连接池大小 |
| `VOLC_SD_BASE_URL` | 火山透传 Provider 地址 |
| `SEEDANCE_BASE_URL` | 声明式 Provider 地址 |
| `KLING_BASE_URL` | 脚本模式 Provider 地址 |
