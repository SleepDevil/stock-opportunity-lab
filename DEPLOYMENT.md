# 部署手册

这份手册用于把 Stock Opportunity Lab 部署到免费或低成本云环境。当前推荐组合是：

- 应用服务：Render Docker Web Service
- 数据库：Neon Free Postgres
- 代码来源：GitHub/GitLab/Bitbucket 仓库

选择这个组合的原因：本项目不是纯前端静态站点，后端依赖 FastAPI、AkShare、pandas，并且策略学习库需要长期持久化。Render 可以用仓库根目录的 `render.yaml` 创建 Docker Web Service；Neon 提供 serverless Postgres、连接池和免费计划，适合先跑演示、回测学习库和小规模自用。

参考官方文档：

- Render Blueprint: https://render.com/docs/infrastructure-as-code
- Render Blueprint YAML: https://render.com/docs/blueprint-spec
- Render CLI: https://render.com/docs/cli
- Render Health Checks: https://render.com/docs/health-checks
- Neon 连接文档: https://neon.com/docs/get-started/connect-neon
- Neon Pricing: https://neon.com/pricing

## 当前仓库已经准备好的内容

- `Dockerfile`：构建 Vite 前端，并由 FastAPI 同源托管 `frontend/dist`。
- `render.yaml`：定义 Render Web Service，使用 Docker runtime、Free plan、`/api/health` 健康检查。
- `.dockerignore`：减少 Docker build context。
- `STOCK_LAB_DATABASE_URL`：线上策略学习库连接串，建议指向 Neon Postgres。
- `STOCK_LAB_DATA_DIR`：行情缓存和报告目录。Render 免费实例文件系统不适合长期保存状态，所以长期记忆必须依赖数据库。

## 你需要先操作的事情

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

### 2. 准备 Render 登录

本机已经检测到 Render CLI：

```bash
~/.local/bin/render --version
```

但当前还没有登录。请在终端运行：

```bash
~/.local/bin/render login
```

它会打开浏览器让你授权。登录完成后，再运行：

```bash
~/.local/bin/render workspaces --output json
```

如果能看到 workspace 列表，就把结果告诉我，或直接告诉我“Render 登录好了”。

如果你有多个 workspace，请选择要部署到哪个 workspace。CLI 设置方式是：

```bash
~/.local/bin/render workspace set <WORKSPACE_ID>
```

### 3. 确认代码已推到 Git 服务

Render Blueprint 需要从 GitHub/GitLab/Bitbucket 读取仓库。请确保当前代码已经推到你准备用于部署的远程仓库和分支。

如果你希望我来整理 commit，请告诉我；我会按本仓库的 Lore Commit Protocol 写提交信息。

## Render Dashboard 部署方式

这是最稳的路径，适合第一次部署：

1. 打开 https://dashboard.render.com 并登录。
2. 点击 `New`，选择 `Blueprint`。
3. 连接当前项目所在的 GitHub/GitLab/Bitbucket 仓库。
4. 选择包含 `render.yaml` 的分支。
5. Blueprint Path 保持默认 `render.yaml`。
6. Render 会识别一个名为 `stock-opportunity-lab` 的 Docker Web Service。
7. 在环境变量里填写：

```text
STOCK_LAB_DATABASE_URL=<你的 Neon pooled connection string>
STOCK_LAB_DATA_DIR=/data
PYTHONUNBUFFERED=1
```

`STOCK_LAB_DATABASE_URL` 不要提交到代码里，只放在 Render 环境变量中。

8. 点击 Deploy Blueprint。
9. 等待构建完成后，打开 Render 分配的 `https://*.onrender.com` 地址。

## 登录后我可以继续执行的命令

登录 Render 后，我可以继续做这些非破坏性检查：

```bash
~/.local/bin/render workspaces --output json
~/.local/bin/render workspace current --output json
~/.local/bin/render blueprints validate ./render.yaml --output json
```

如果你已经在 Dashboard 创建了服务，我还可以继续查服务和部署状态：

```bash
~/.local/bin/render services --output json
~/.local/bin/render deploys list <SERVICE_ID> --output json
```

如果你确认要触发重新部署，我会在你明确说“可以触发部署”后运行：

```bash
~/.local/bin/render deploys create <SERVICE_ID> --wait --output json
```

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
- 线上接入大模型时，API key 只放在 Render 环境变量，不能写入仓库。
- 如果使用第三方模型，需要控制 timeout、重试、成本上限和返回格式，避免一次盘后扫描被模型调用拖垮。

## 当前阻塞点

我现在能完成本地构建和静态检查，但不能替你完成以下认证步骤：

- Render CLI 未登录，命令返回 `run render login to authenticate`。
- Render Blueprint 校验需要先有 active workspace 或显式 workspace ID。
- Neon 数据库需要你登录后创建并复制连接串。
- 本机未安装 Docker CLI，所以无法在本机直接构建镜像；Render 云端会根据 `Dockerfile` 构建。

你完成 Render 登录和 Neon 连接串准备后，告诉我：

```text
Render 登录好了，Neon 连接串也准备好了
```

然后我会继续做 Blueprint 校验、部署状态检查和线上验收。

## Render 登录 DNS 超时排查

如果运行：

```bash
~/.local/bin/render login
```

报错：

```text
Error: Post "https://api.render.com/v1/device-grant": dial tcp: lookup api.render.com: i/o timeout
```

这通常不是账号问题，而是本机 DNS、VPN、代理或公司网络出口没有及时解析 `api.render.com`。

先做三步检查：

```bash
dig +time=3 +tries=1 api.render.com
nslookup api.render.com 1.1.1.1
curl -Iv --connect-timeout 10 https://api.render.com/v1/device-grant
```

判断方式：

- `dig` 或 `nslookup` 超时：优先处理 DNS/VPN/代理。
- `curl` 能连上并返回 `HTTP/2 405` 且有 `allow: POST`：说明网络可达，可以重新运行 `render login`。
- 浏览器也打不开 `https://dashboard.render.com`：切换网络或 VPN 后再试。

macOS 上可尝试：

```bash
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
```

如果你使用公司 VPN、Clash、Surge、Little Snitch、LuLu 等网络工具，先重启对应工具，或临时切换规则，让以下域名走可访问外网的线路：

```text
api.render.com
dashboard.render.com
render.com
```

如果 DNS 仍持续超时，可以临时把当前网络服务的 DNS 改成公共 DNS。先查看服务名：

```bash
networksetup -listallnetworkservices
```

如果服务名是 `Wi-Fi`：

```bash
networksetup -setdnsservers Wi-Fi 1.1.1.1 8.8.8.8
```

恢复自动 DNS：

```bash
networksetup -setdnsservers Wi-Fi Empty
```

网络恢复后再运行：

```bash
~/.local/bin/render login
~/.local/bin/render workspaces --output json
```
