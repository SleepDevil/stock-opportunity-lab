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
| `STOCK_LAB_AI_COMMAND` | 可选外部 AI 命令适配器 |

所有密钥必须由部署平台的 Secret 管理，不得写入镜像、前端 Bundle、日志或 Git 仓库。

## 数据持久化

- 单机部署可以挂载 `STOCK_LAB_DATA_DIR` 并使用 SQLite。
- 多实例部署应配置外部 Postgres。
- 行情缓存和报告可以重建；学习记录、用户设置和参数实验应定期备份。

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
