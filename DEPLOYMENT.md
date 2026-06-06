# 部署手册

这份手册用于把 Stock Opportunity Lab 部署到免费云环境。当前推荐组合是：

- 应用服务：Vercel
- 数据库：Neon Free Postgres
- 代码来源：GitHub 仓库

选择这个组合的原因：用户底线是不绑定付款方式；Render Blueprint 在当前账号下会要求补充 payment method，因此默认路径切换为 Vercel。Vercel 官方 FastAPI 文档支持根目录 `server.py` 暴露 `FastAPI` 实例；本仓库用 `server.py` 导入后端应用，并让 FastAPI 同源托管 `frontend/dist`。

参考官方文档：

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
- `STOCK_LAB_DATABASE_URL`：线上策略学习库连接串，建议指向 Neon Postgres。
- `STOCK_LAB_DATA_DIR`：行情缓存和报告目录。Vercel 默认使用 `/tmp/stock-opportunity-lab`。

Docker/Render 配置仍保留，作为以后愿意绑定付款方式或迁移到容器平台时的可选方案。

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

### 2. 准备 Vercel 登录

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

部署前或部署后都可以设置数据库环境变量：

```bash
npx vercel@latest env add STOCK_LAB_DATABASE_URL production
```

按提示粘贴 Neon pooled connection string。设置后需要重新部署一次：

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
