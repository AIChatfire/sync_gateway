# Sync Gateway — 同步任务映射服务

基于同样的四模态架构（透传/声明式/表达式/脚本），专为同步阻塞任务（文生图、短文本生成等）设计。

## 特性

- **四模态转换**：透传(passthrough) / 声明式(request_map) / 表达式(expr) / 脚本(script)
- **Nacos 热更新**：配置推送秒级生效
- **快照回滚**：保留最近 5 个版本，支持 `/admin/rollback` 手动回退
- **错误隔离**：单个 Provider 脚本错误不影响其他 Provider
- **健康检查**：`GET /health` 展示各 Provider 状态与模式

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
├── tests/                  # 测试
├── scripts/                # 运维/初始化脚本
├── docs/                   # 文档
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

## 调用示例

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
# 健康检查
GET /health

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
| `VOLC_SD_BASE_URL` / `VOLC_SD_API_KEY` | 火山透传 Provider |
| `SEEDANCE_BASE_URL` / `SEEDANCE_API_KEY` | 声明式 Provider |
| `KLING_BASE_URL` / `KLING_API_KEY` | 脚本模式 Provider |
