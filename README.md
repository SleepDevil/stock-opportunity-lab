# Stock Opportunity Lab

一个本地 Web 应用：用 AkShare 在盘后筛选 A 股机会，生成第二天买入计划，并把前一日计划和次日实际走势做回测对比。

## 技术栈

- Frontend: React 19, Vite, TypeScript, Mantine, lucide-react
- Backend: FastAPI, pandas, AkShare
- Storage: SQLite/Postgres 学习库 + 本地 CSV/Markdown 行情和报告缓存，目录在 `data/`

系统不连接券商账号，不保存交易凭证，不自动下单。

## 启动

```bash
cd /Users/sleepdevil1/xigua-fe/stock-opportunity-lab
npm run setup
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

后端 API：

```text
http://127.0.0.1:8000
```

## 使用流程

1. 盘后选择日期，点击“盘后扫描”。
2. 查看候选股、分数、成交额、换手率、量比、市值、计划低吸价、买入上限、高开放弃价、止损参考价。
3. 第二天盘后选择“选股日期”和“实际日期”，点击“运行回测”。
4. 查看触发率、胜率、平均浮盈、最大回撤，以及每只股票为什么触发或没有触发。
5. AI/规则解释区会展示受控分析：默认使用规则化解释；如配置 `STOCK_LAB_AI_COMMAND`，可把受控 JSON payload 交给外部大模型命令处理。
6. “策略进化”会把回测样本、人工复盘、参数实验版本和 baseline/proposed 后续表现写入数据库，形成长期实验链。

## 产品与设计文档

- 产品 PRD：`docs/prd/stock-opportunity-lab-prd.md`
- 技术架构：`architecture.md`
- Google Stitch 生成提示词：`docs/prompts/google-stitch-stock-opportunity-lab.md`
- 设计结构树：`docs/design-tree/stock-opportunity-lab.md`
- 设计契约：`DESIGN.md`

## 部署

当前推荐保留两条免费部署路径：

- 中国大陆访问优先：EdgeOne Pages + Neon Free Postgres。EdgeOne Pages 会分配默认项目域名，不需要先准备自定义域名。
- 海外访问和现有线上演示：Vercel + Neon Free Postgres。Vercel 不需要绑定付款方式，但 `.vercel.app` 在中国大陆访问不稳定。

详细部署操作见 `DEPLOYMENT.md`。

仓库已包含：

- `server.py`：Vercel FastAPI 入口，导入 `backend/app/main.py` 中的 `app`。
- `requirements.txt`：Vercel Python Runtime 安装后端依赖。
- `vercel.json`：构建 Vite 前端，并把所有路由交给 FastAPI 同源托管。
- `.vercelignore`：排除本地缓存、虚拟环境、node_modules 和运行数据。
- `edgeone.json`：EdgeOne Pages 构建配置，输出 Vite 静态资源并部署 Python Cloud Functions。
- `cloud-functions/api/[[default]].py`：EdgeOne FastAPI 适配入口，把 EdgeOne 的 `/api/*` 路由转给现有后端。
- `cloud-functions/[[default]].py`：EdgeOne 前端深链接兜底入口，用于刷新 `/backtest`、`/settings` 这类 SPA 路由。
- `scripts/build-edgeone.mjs`：EdgeOne 构建脚本，复制后端源码到函数目录并构建前端。
- `Dockerfile`：构建 Vite 前端，并由 FastAPI 同源托管静态产物。
- `render.yaml`：Render 可选部署配置；当前不作为默认路径。
- `STOCK_LAB_DATA_DIR`：可把行情缓存和报告目录切到云平台运行目录，默认本地 `data/`。
- `STOCK_LAB_DATABASE_URL`：策略学习库连接串。不配置时使用 `data/stock_lab.sqlite3`；线上建议填 Neon/Supabase 的 Postgres URL。
- `STOCK_LAB_AI_COMMAND`：可选外部大模型命令。系统会把受控 JSON payload 写入 stdin，并使用命令 stdout 作为解释文本。
- `STOCK_LAB_FEISHU_APP_ID`：飞书机器人应用 ID，默认使用 `cli_a6f82b2e17f6100c`。
- `STOCK_LAB_FEISHU_APP_SECRET`：飞书机器人应用密钥，只能放在本地 `.env` 或云平台环境变量里，不能提交到仓库。
- `STOCK_LAB_CLIENT_AUTH_SECRET`：前端通知设置接口的 CSRF/HMAC 签名密钥；线上建议单独配置，不配置时会退到飞书 app secret。

EdgeOne Pages 部署流程：

1. 把仓库推到 GitHub。
2. 在 Neon 创建免费 Postgres 数据库，复制 pooled connection string。
3. 在 EdgeOne Pages 新建项目，导入 `SleepDevil/stock-opportunity-lab`。
4. 让项目使用仓库里的 `edgeone.json`，构建命令会自动运行 `node scripts/build-edgeone.mjs`。
5. 在 EdgeOne 环境变量里填入 `STOCK_LAB_DATABASE_URL=postgresql://...`、`STOCK_LAB_CLIENT_AUTH_SECRET=...`，如需飞书通知再填 `STOCK_LAB_FEISHU_APP_SECRET=...`。
6. 部署完成后访问 EdgeOne 分配的默认项目域名。

Vercel 部署流程：

1. 把仓库推到 GitHub。
2. 在 Neon 创建免费 Postgres 数据库，复制 pooled connection string。
3. 用 Vercel CLI 或 Dashboard 导入本仓库。
4. 在 Vercel 环境变量里填入 `STOCK_LAB_DATABASE_URL=postgresql://...`、`STOCK_LAB_FEISHU_APP_SECRET=...` 和 `STOCK_LAB_CLIENT_AUTH_SECRET=...`。
5. 部署完成后访问 Vercel 分配的 `https://*.vercel.app` 地址。

Vercel 和 EdgeOne 的函数文件系统都是临时的。未配置 `STOCK_LAB_DATABASE_URL` 时，应用仍可启动并使用临时 SQLite 做演示；但长期学习记忆、策略实验链和用户反馈必须使用外部 Postgres。

## 数据库

学习库现在由 `backend/app/services/learning_store.py` 管理：

- `learning_records`：每条盘后推荐在次日的验证结果、系统归因和用户复盘。
- `user_settings`：按邮箱保存简单账户 profile，包括通知邮箱、板块排除开关和排除范围。
- `strategy_experiments`：每次参数建议的稳定实验版本。
- `strategy_experiment_outcomes`：同一实验版本下 baseline/proposed 的后续胜率、平均收益和回撤对照。

旧的 `data/learning/records.json` 会在首次读取时自动导入数据库；旧的 `data/settings.json` 会按邮箱导入 `user_settings`。后续新写入以数据库为准。前端仍会在浏览器本地保存当前邮箱和板块偏好作为快速回退，但长期配置以数据库为准。

本地默认无需配置：

```text
data/stock_lab.sqlite3
```

线上推荐：

```text
STOCK_LAB_DATABASE_URL=postgresql://USER:PASSWORD@HOST/DB?sslmode=require
```

## 大模型能力

当前系统默认没有直接绑定某个大模型供应商。`backend/app/services/ai.py` 提供两层能力：

- 默认：`deterministic_explanation()` 生成规则化解释，优点是稳定、可测、不会编造未提供的信息。
- 可选：设置 `STOCK_LAB_AI_COMMAND` 后，系统把包含候选、回测、学习摘要的 JSON payload 传给外部命令，由你接入任意 LLM CLI 或网关。

技术上建议大模型只做“解释、归因假设、复盘摘要、人工反馈结构化”，不要让模型直接改策略参数或宣称 80% 胜率。策略是否进化必须由数据库里的跨行情样本、A/B 实验表现和回撤指标验证。

## 公众号消息知识

“消息异动”页新增了公众号知识入口：

- 保存订阅源：公众号名、样例文章 URL、可选 Feed URL。
- 导入文章：填写微信公众号文章 URL；如果当前网络无法直接访问微信文章，也可以粘贴文章 HTML。
- 知识提取：系统会保存标题、正文、摘要、主题标签、机会点、风险点和市场相关度。

微信没有稳定公开接口可订阅任意公众号的全部历史和后续消息。官方发布接口主要面向公众号自身或授权后的公众号；RSSHub 文档也明确提示公众号直接抓取困难。因此当前实现采用“手动 URL 导入 + 合规 feed 预留”的简洁形态，不把系统建立在不稳定的反爬链路上。

## 注意

AkShare 当前全市场快照适合每天盘后缓存。要严格回放某个历史日的全市场筛选，必须当天已经有 `data/raw/spot_YYYYMMDD.csv` 或 `data/reports/screen_YYYYMMDD.csv`。否则历史全市场市值和量比无法完全还原。

## 验证

```bash
npm run test
```
