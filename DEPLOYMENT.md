# 部署手册

这份手册用于把 Stock Opportunity Lab 部署到免费云环境。当前保留三条路线：

- 永久静态入口：GitHub Pages
- 中国大陆临时预览：EdgeOne Pages
- 完整功能入口：Vercel
- 数据库：Neon Free Postgres
- 代码来源：GitHub 仓库

选择这个组合的原因：用户底线是不绑定付款方式；Render Blueprint 在当前账号下会要求补充 payment method。Vercel 可以免费部署完整 FastAPI 后端，但 `.vercel.app` 在中国大陆访问不稳定。EdgeOne Pages 在含中国大陆加速区域未绑定自定义域名时，系统预览链接有效期只有 3 小时，适合临时验收，不适合作为长期入口。GitHub Pages 提供永久静态入口，但不能连接 Python 后端、数据库或 AkShare 采集。长期学习库继续用 Neon Postgres，避免把学习数据写入临时函数文件系统。

参考官方文档：

- EdgeOne Pages Python Runtime: https://pages.edgeone.ai/document/python
- EdgeOne Pages edgeone.json: https://pages.edgeone.ai/zh/document/edgeone-json
- EdgeOne Pages Cloud Functions: https://pages.edgeone.ai/document/cloud-functions
- EdgeOne Pages Domain Management: https://pages.edgeone.ai/document/domain-overview
- GitHub Pages custom workflows: https://docs.github.com/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
- GitHub Pages REST API: https://docs.github.com/en/rest/pages/pages
- Vercel FastAPI: https://vercel.com/docs/frameworks/backend/fastapi
- Vercel Python Runtime: https://vercel.com/docs/functions/runtimes/python
- Vercel Project Configuration: https://vercel.com/docs/project-configuration
- Vercel Function Duration: https://vercel.com/docs/functions/configuring-functions/duration
- Neon 连接文档: https://neon.com/docs/get-started-with-neon/connect-neon
- Neon Pricing: https://neon.com/pricing

## 当前仓库已经准备好的内容

- `server.py`：Vercel FastAPI 入口，导入 `backend/app/main.py` 里的 `app`。
- `requirements.txt`：Vercel Python Runtime 安装 FastAPI、pandas、AkShare、psycopg 等后端依赖。
- `vercel.json`：执行 `npm --prefix frontend ci && npm --prefix frontend run build`，并把所有请求重写到 `server.py`。
- `.vercelignore`：排除 `.venv`、`node_modules`、`data`、`artifacts` 等无需上传的本地文件。
- `edgeone.json`：EdgeOne Pages 构建配置，安装前端依赖、执行 `node scripts/build-edgeone.mjs`、输出 `frontend/dist`，并把 Python Cloud Functions 部署到上海/香港。
- `cloud-functions/api/[[default]].py`：EdgeOne 轻后端 HTTP 入口。它直接提供健康检查、配置和只读学习摘要；盘后扫描、实时行情、财务采集、用户设置写入和公众号写入保留给 Vercel/Docker 或后续独立 worker。
- `cloud-functions/requirements.txt`：EdgeOne Python Runtime 轻部署不安装第三方 Python 依赖，避免触发包体积限制。
- `scripts/build-edgeone.mjs`：构建 Vite 前端，静态产物输出到 `frontend/dist`。
- `.github/workflows/github-pages.yml`：GitHub Pages 静态镜像发布流程。它设置 `VITE_STOCK_LAB_STATIC_MODE=true`，让前端在没有 `/api` 后端的情况下显示长期可访问的只读占位体验。
- `STOCK_LAB_DATABASE_URL`：线上策略学习库连接串，建议指向 Neon Postgres。
- `STOCK_LAB_DATA_DIR`：行情缓存和报告目录。Vercel 默认使用 `/tmp/stock-opportunity-lab`；EdgeOne 适配入口也会默认设置为 `/tmp/stock-opportunity-lab`。
- `STOCK_LAB_FEISHU_APP_SECRET`：飞书机器人应用密钥，用于后端直接调用飞书 OpenAPI 发送通知。
- `STOCK_LAB_CLIENT_AUTH_SECRET`：通知设置接口的 CSRF/HMAC 签名密钥，建议和飞书密钥分开配置。

Docker/Render 配置仍保留，作为以后愿意绑定付款方式或迁移到容器平台时的可选方案。

## GitHub Pages 永久静态入口

GitHub Pages 用于解决“没有自定义域名时入口链接会过期”的问题。它的固定地址是：

```text
https://sleepdevil.github.io/stock-opportunity-lab/
```

限制：

- 只部署 Vite 静态产物，不部署 Python/FastAPI。
- 不连接 Neon 数据库，不读取或写入用户设置、公众号知识、策略学习记录。
- 所有需要后端的动作会提示“GitHub Pages 静态镜像不可用”。

启用条件：

1. 仓库必须是 public。
2. GitHub Pages 的 build type 设置为 `workflow`。
3. 推送到 `main` 后，`Deploy GitHub Pages` workflow 自动构建并发布 `frontend/dist`。

## 你需要准备的事情

### 1. 准备 Neon 数据库

1. 打开 https://console.neon.tech 并登录。
2. 新建一个 Project，名称可以用 `stock-opportunity-lab`。
3. 创建完成后进入 Connection details。
4. 选择 pooled connection string。
5. 复制形如下面的连接串：

```text
postgresql://USER:PASSWORD@HOST.neon.tech/DB?sslmode=require
```

如果 Neon 页面给出的连接串没有 `sslmode=require`，请在末尾补上：

```text
?sslmode=require
```

如果连接串已经有其他查询参数，则追加：

```text
&sslmode=require
```

`STOCK_LAB_DATABASE_URL` 不能提交到仓库，只能放在 Vercel 环境变量中。

### 2. 准备 EdgeOne Pages 项目

1. 打开 EdgeOne Pages 控制台并登录。
2. 新建 Pages 项目，导入 GitHub 仓库 `SleepDevil/stock-opportunity-lab`。
3. 如果页面让你填写构建配置，保持仓库内 `edgeone.json` 为准：

```text
Install Command: npm --prefix frontend ci --include=optional
Build Command: node scripts/build-edgeone.mjs
Output Directory: frontend/dist
Node Version: 22.17.1
```

4. 在环境变量里添加：

```text
STOCK_LAB_DATABASE_URL=<你的 Neon pooled connection string>
STOCK_LAB_CLIENT_AUTH_SECRET=<随机生成的长密钥>
STOCK_LAB_FEISHU_APP_SECRET=<飞书机器人 app secret，可选>
STOCK_LAB_FEISHU_APP_ID=<飞书机器人 app id，可选>
```

5. 部署完成后访问 EdgeOne 预览链接，检查：

```text
https://<EdgeOne 默认域名>/api/health
https://<EdgeOne 默认域名>/api/config
https://<EdgeOne 默认域名>/
```

EdgeOne Cloud Functions 当前 Python 运行时是 3.10，单函数包大小限制为 128 MB，单次请求最长 120 秒。EdgeOne 版本不打包第三方 Python 依赖，适合承载前端、健康检查和配置等轻能力；盘后全市场扫描、实时行情采集、财务报表抓取、用户设置写入和公众号知识写入继续使用 Vercel/Docker 路线，后续应拆到独立 worker。EdgeOne 官方配置文档说明静态 rewrite 不支持 SPA 前端路由重写，所以默认域下请从 `/` 进入应用，直接刷新 `/backtest`、`/settings` 这类深链接不作为 EdgeOne 轻部署验收项。

EdgeOne 官方域名文档说明：当项目加速区域选择“中国大陆可用区”或“全球可用区（含中国大陆）”时，必须使用系统生成的 preview URL 访问，链接有效期只有 3 小时，超时会返回 401。可以在控制台重新点击 preview 生成新链接；真正长期稳定的 EdgeOne 入口需要绑定自定义域名。含中国大陆加速区域的自定义域名还涉及 ICP 备案要求。

### 3. 准备 Vercel 登录

本地可以使用 Vercel CLI：

```bash
npx vercel@latest login
```

登录完成后，可以验证：

```bash
npx vercel@latest whoami
```

如果 CLI 要求浏览器授权，请在浏览器里完成登录后回到终端。

## Vercel CLI 部署方式

仓库根目录运行：

```bash
npx vercel@latest --prod --yes
```

首次部署时，Vercel CLI 会把本地目录链接为一个 Vercel project。项目名可以使用：

```text
stock-opportunity-lab
```

部署前或部署后都可以设置数据库和飞书环境变量：

```bash
npx vercel@latest env add STOCK_LAB_DATABASE_URL production
npx vercel@latest env add STOCK_LAB_FEISHU_APP_SECRET production
npx vercel@latest env add STOCK_LAB_CLIENT_AUTH_SECRET production
```

按提示分别粘贴 Neon pooled connection string、飞书机器人 app secret 和客户端鉴权签名密钥。设置后需要重新部署一次：

```bash
npx vercel@latest --prod --yes
```

如果只是先验证公网可访问，未配置数据库也可以部署；应用会临时使用 `/tmp/stock-opportunity-lab/stock_lab.sqlite3`，但这种数据不会长期保留。

## Vercel Dashboard 部署方式

1. 打开 https://vercel.com/dashboard 并登录。
2. 点击 `Add New` -> `Project`。
3. 导入 `SleepDevil/stock-opportunity-lab`。
4. Framework Preset 保持自动识别或选择 Other。
5. Build Command 使用仓库里的 `vercel.json`，即：

```bash
npm --prefix frontend ci && npm --prefix frontend run build
```

6. 在 Environment Variables 添加：

```text
STOCK_LAB_DATABASE_URL=<你的 Neon pooled connection string>
STOCK_LAB_FEISHU_APP_SECRET=<飞书机器人 app secret>
STOCK_LAB_CLIENT_AUTH_SECRET=<随机生成的长密钥>
```

7. 点击 Deploy。

## 部署后验收

部署成功后检查这些地址：

```text
https://<你的服务域名>/api/health
https://<你的服务域名>/api/config
https://<你的服务域名>/backtest
https://<你的服务域名>/alerts
```

期望结果：

- `/api/health` 返回 ready。
- `/api/config` 里 `database_url` 应该是脱敏后的 Postgres URL，不能暴露密码。
- `/api/config` 里 `feishu_app_secret` 和 `client_auth_secret` 只能是 `***` 或 `null`，不能暴露真实密钥。
- `/settings` 保存账户邮箱和板块偏好后，Neon 的 `user_settings` 表应出现对应记录。
- `/backtest` 能看到策略进化、学习样本、实验对照相关入口。
- `/alerts` 能看到公众号知识入口，并能保存 `21世纪经济报道` 订阅源。

## 大模型接入能力

当前系统已经有大模型接入点，但默认不绑定供应商：

- 默认模式：`backend/app/services/ai.py` 使用规则化解释，稳定、可测试、不编造未提供的信息。
- 可选模式：设置 `STOCK_LAB_AI_COMMAND` 后，后端会把受控 JSON payload 写入外部命令 stdin，并把 stdout 当作解释文本返回。

一个典型接入方式是写一个命令行 wrapper：

```bash
export STOCK_LAB_AI_COMMAND="/app/scripts/stock-lab-llm"
```

这个 wrapper 读取 stdin JSON，调用你选择的大模型 API，然后输出中文解释。

技术边界建议：

- 大模型适合做解释、归因假设、复盘摘要、人工反馈结构化。
- 大模型不应该直接宣称达到 80% 胜率，也不应该绕过实验链直接改策略。
- 策略进化必须由数据库中的跨行情样本、baseline/proposed 对照、胜率、收益、回撤共同验证。
- 线上接入大模型时，API key 只放在 Vercel 环境变量，不能写入仓库。
- 如果使用第三方模型，需要控制 timeout、重试、成本上限和返回格式，避免一次盘后扫描被模型调用拖垮。

## 当前限制

- Vercel Functions 的文件系统是临时的，所以长期学习库必须配置 Neon 或其他外部 Postgres。
- AkShare 全市场扫描可能接近云函数耗时上限；这版先支持公网演示和轻量使用，后续如果要稳定跑每日盘后任务，应把扫描任务迁到定时任务/队列或容器服务。
- 如果 Vercel 构建提示 Python bundle 超过限制，需要把 AkShare 采集层拆到独立 worker，Web 应用只保留报告查询和学习库能力。
