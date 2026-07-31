# 部署指南

Stock Opportunity Lab 可以部署到任意支持 Docker、HTTPS 和持久化环境变量的平台。公开仓库不保存实际域名、账户、流水线 ID 或生产凭证。

## Docker

构建并运行：

```bash
docker build -t stock-opportunity-lab .
docker run --rm \
  -p 8000:8000 \
  -v stock-lab-data:/data \
  -e STOCK_LAB_CLIENT_AUTH_SECRET=replace-with-a-random-secret \
  stock-opportunity-lab
```

健康检查：

```bash
curl -fsS http://127.0.0.1:8000/api/health
```

期望返回：

```json
{"ok":true,"message":"ready"}
```

## 环境变量

| 变量 | 用途 |
| --- | --- |
| `PORT` | HTTP 端口，默认 `8000` |
| `STOCK_LAB_DATA_DIR` | 本地缓存与 SQLite 数据目录 |
| `STOCK_LAB_DATABASE_URL` | 可选 Postgres 连接串 |
| `STOCK_LAB_CLIENT_AUTH_SECRET` | CSRF/HMAC 签名密钥，生产环境必须使用随机值 |
| `STOCK_LAB_FEISHU_APP_ID` | 可选通知应用 ID |
| `STOCK_LAB_FEISHU_APP_SECRET` | 可选通知应用密钥 |
| `STOCK_LAB_WATCHLIST_COMMENTARY_FEISHU_ENABLED` | 是否默认开启自选锐评群推送；`true`/`false` |
| `STOCK_LAB_WATCHLIST_COMMENTARY_FEISHU_CHAT_ID` | 默认订阅群；支持数字群 ID 或 `oc_` 开头的 open_chat_id |
| `STOCK_LAB_WATCHLIST_COMMENTARY_PLATFORM_URL` | 卡片内个股分析链接的网站根地址 |
| `STOCK_LAB_WATCHLIST_COMMENTARY_DEFAULT_WATCHLIST` | FaaS 首次启动时的默认自选 JSON 数组；Web 保存后优先使用服务端数据库中的名单 |
| `STOCK_LAB_WATCHLIST_COMMENTARY_TIMER_NAME` | FaaS Timer 触发器名称；创建触发器时须把 `{"timer_name":"同一名称"}` 配为“触发消息”，服务端仅接受消息中名称完全匹配的标准 Timer CloudEvent |
| `STOCK_LAB_AI_PROVIDER` | 锐评生成后端：`auto`、`zhipu`、`command` 或 `rules`；默认 `auto` |
| `STOCK_LAB_ZHIPU_API_KEY` | 智谱开放平台 API Key；配置后默认调用免费模型 |
| `STOCK_LAB_ZHIPU_MODEL` | 智谱模型编码，默认 `glm-4.7-flash` |
| `STOCK_LAB_ZHIPU_BASE_URL` | 可选智谱兼容端点，默认官方 `https://open.bigmodel.cn/api/paas/v4` |
| `STOCK_LAB_AI_TIMEOUT_SECONDS` | 模型请求超时，默认 30 秒，限制在 3—120 秒 |
| `STOCK_LAB_AI_COMMAND` | 兼容旧版的可选外部 AI 命令适配器 |

所有密钥必须由部署平台的 Secret 管理，不得写入镜像、前端 Bundle、日志或 Git 仓库。

`auto` 模式优先使用智谱 API，其次使用已配置的旧命令适配器，最后降级为行情规则。生产环境建议保留该默认值，避免模型临时限流导致定时锐评整体失败。

## 数据持久化

- 单机部署可以挂载 `STOCK_LAB_DATA_DIR` 并使用 SQLite。
- 多实例部署应配置外部 Postgres。
- 行情缓存和报告可以重建；学习记录、用户设置和参数实验应定期备份。

自选锐评名单和定时投递幂等记录也使用同一数据库。FaaS 多实例或需要跨发布保留用户编辑时，应配置外部 Postgres；仅使用实例 `/tmp` SQLite 时，应同时配置默认自选环境变量作为发布后的安全回退。

## Web 部署验收

部署完成后检查：

1. `/api/health` 返回 `ready`。
2. `/`、`/backtest`、`/alerts` 等前端路由正常回退到 `index.html`。
3. `/api/config` 对数据库密码、通知密钥和客户端鉴权密钥只返回掩码。
4. HTTPS、CORS、持久化存储和备份策略符合部署环境要求。

## 桌面构建

默认桌面客户端包含本地 FastAPI sidecar，不依赖部署后的 Web API：

```bash
npm run desktop:build
```

GitHub Actions 使用以下仓库 Secrets：

- `TAURI_SIGNING_PRIVATE_KEY`：Tauri updater 私钥。
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`：私钥密码；无密码密钥可不配置。

如需构建连接自建 HTTPS API 的定制客户端，可在本地设置 `VITE_STOCK_LAB_API_BASE_URL`。这个地址会写入安装包，不应通过公开构建或公开 Release 分发敏感端点。

普通 PR 和 `main` 提交只生成 Actions Artifacts。只有与 `src-tauri/tauri.conf.json` 版本一致的 `desktop-vX.Y.Z` 标签才发布签名更新；全部平台成功后 Release 才会成为 Latest。

## 安全检查

在公开代码或发布新版本前：

```bash
git grep -nI -i -E 'password|secret|token|internal'
git grep -nI -E 'https?://'
```

还应使用专门的 Secret Scanner 检查完整 Git 历史。若敏感信息曾进入历史，仅删除当前文件并不够；应重写历史或从干净快照重新建立公开仓库，并轮换已经暴露的凭证。
