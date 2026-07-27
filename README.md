# Stock Opportunity Lab

一个 Web 与桌面客户端并存的本地优先量化研究应用：使用公开行情数据筛选 A 股机会，生成次日交易计划，并通过回测和人工复盘持续验证策略。

## 能力

- 盘后机会筛选、买入计划与次日验证
- 个股行情、财务数据、公告和资讯分析
- 板块资金、盘中异动与公众号知识整理
- SQLite / Postgres 学习库和参数实验
- React Web 应用与 Tauri 2 桌面客户端
- 可选通知机器人与外部 AI 命令适配器

系统不连接券商账号，不保存交易凭证，也不会自动下单。所有结果仅用于研究，不构成投资建议。

## 技术栈

- Frontend: React 19、Vite、TypeScript、Mantine、TanStack Query
- Backend: FastAPI、pandas、AkShare
- Desktop: Tauri 2，共用 React 前端
- Storage: SQLite 或 Postgres

## 快速开始

需要 Node.js 22 和 Python 3.12：

```bash
git clone https://github.com/SleepDevil/stock-opportunity-lab.git
cd stock-opportunity-lab
npm run setup
npm run dev
```

打开 `http://127.0.0.1:5173`。后端 API 默认监听 `http://127.0.0.1:8000`。

`npm run dev` 会启动后端、前端和可选的公众号网关；只需要主应用时运行：

```bash
npm run dev:core
```

## 配置

敏感配置只应通过环境变量或部署平台的 Secret 管理，不要提交 `.env`：

```text
STOCK_LAB_DATA_DIR=/path/to/data
STOCK_LAB_DATABASE_URL=postgresql://USER:PASSWORD@HOST/DB?sslmode=require
STOCK_LAB_CLIENT_AUTH_SECRET=replace-with-a-random-secret
STOCK_LAB_FEISHU_APP_ID=optional-app-id
STOCK_LAB_FEISHU_APP_SECRET=optional-app-secret
STOCK_LAB_AI_COMMAND=optional-command
```

未配置数据库连接时使用 `data/stock_lab.sqlite3`。本地开发命令默认忽略远程数据库地址，避免误连生产数据。

## 桌面客户端

开发模式：

```bash
npm run desktop:dev
```

构建当前平台的自包含安装包：

```bash
npm run desktop:build
```

构建脚本会先用 PyInstaller 打包本地 FastAPI sidecar，客户端只连接回环地址，不需要在安装包中保存任何部署端点。确实需要连接自建服务时仍可在本地构建前设置 `VITE_STOCK_LAB_API_BASE_URL=https://api.example.com`；该值会进入前端 Bundle，因此不应把敏感或仅供内部使用的地址交给公开 CI。

桌面客户端会检查 GitHub Releases 中的签名更新。macOS 应用菜单提供 `Check for Updates…`，发现新版本后主窗口会显示更新按钮。完整构建与签名流程见 [`docs/desktop-client.md`](docs/desktop-client.md)。

## 部署

仓库包含通用 `Dockerfile` 和 `render.yaml`。任意支持 Docker 与持久化环境变量的平台都可以部署：

```bash
docker build -t stock-opportunity-lab .
docker run --rm -p 8000:8000 -v stock-lab-data:/data stock-opportunity-lab
```

FastAPI 同时提供 `/api/*` 和构建后的前端静态文件。生产环境应配置持久化数据库、随机鉴权密钥、HTTPS 和定期备份。详见 [`DEPLOYMENT.md`](DEPLOYMENT.md)。

## 文档

- [技术架构](architecture.md)
- [桌面客户端](docs/desktop-client.md)
- [产品使用手册](docs/product-user-manual.md)
- [量化回测操作手册](docs/quant-backtest-operation-manual.md)
- [产品 PRD](docs/prd/stock-opportunity-lab-prd.md)

## 测试

```bash
npm test
```

该命令依次执行后端测试、前端测试与生产构建，以及 Rust/Tauri 测试。

## License

在添加明确许可证前，保留所有权利。
