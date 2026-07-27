# Tauri 2 桌面客户端

## 目标

Stock Opportunity Lab 同时保留两种入口：

- Web：部署和访问灵活，适合完整研究工作台及局域网访问。
- 桌面客户端：不依赖浏览器窗口，负责原生窗口、托盘和桌面悬浮框。

两种入口不是两套产品。React 页面、FastAPI 服务、SQLite 模型、行情缓存逻辑和测试全部共用。

## 目录

```text
frontend/                 # Web 与 Tauri 共用的 React/Vite 应用
backend/                  # Web 与桌面客户端共用的 FastAPI 代码
src-tauri/                # Tauri 2 原生壳
```

## 运行方式

Web 完整开发环境：

```bash
npm run dev
```

Tauri 桌面开发环境：

```bash
npm run desktop:dev
```

桌面开发模式由 Tauri 启动 `npm run dev:core`，窗口加载 Vite，API 使用项目里的 Python 虚拟环境。公众号网关需要时使用 `npm run dev:wechat` 独立启动。

生产安装包：

```bash
npm run desktop:build
```

生产构建分成两步：

1. `desktop:sidecar` 使用 PyInstaller 把 FastAPI、行情依赖和本地存储逻辑打成当前平台的 sidecar。
2. `build:desktop:web` 构建共享 React 页面，默认连接本机 `127.0.0.1:8765`。
3. Tauri 把页面、原生壳和 sidecar 组合成当前平台安装包。

安装包仍是平台相关产物，因此 macOS arm64、macOS x64、Windows x64 和 Linux x64 安装包分别在对应架构的 runner 构建。用户无需预装 Python 或另行启动后端。

## 运行时

开发模式：

```text
Tauri WebView -> Vite :5173 -> Vite proxy -> FastAPI :8000
```

生产模式：

```text
Tauri WebView -> bundled React assets
                -> loopback FastAPI sidecar :8765
                -> app data directory + local SQLite/cache
```

客户端启动时会检查 `/api/health`，sidecar 准备好后才挂载完整路由；API 不可达时会进入明确的错误态并允许重新连接，不会无限显示 loading。定制构建仍可设置 `VITE_STOCK_LAB_API_BASE_URL` 改用自建 HTTPS API，但该地址会进入前端 Bundle，不应用于公开分发敏感端点。

## 悬浮窗与托盘

桌面版创建两个原生窗口：

- `main`：完整研究工作台，与 Web 版共用全部业务路由。
- `widget`：可拖拽、可缩放的行情悬浮窗，默认置顶并停靠在当前屏幕右上角。

悬浮窗使用 `/desktop-widget` 轻量路由，包含“自选行情”和“今日机会”两个视图。“自选行情”顶部是可切换的主行情卡，默认显示上证指数最新点位、涨跌幅、沪深两市当日成交额和分时走势；在卡片上单击右键，可改为显示任一当前自选股，选择会保存在客户端本地。股票模式显示该股当日成交额与分时走势，同时上证指数会与该股票交换到原来的列表位置，确保指数和每只自选股都只出现一次；被选中的股票移出自选后自动回退到上证指数。标题栏空白区域支持拖拽移动窗口，窗口四边和四角支持原生缩放，最小尺寸为 `320 × 360`；移动和缩放后的状态会被保存。刷新、置顶切换、隐藏由右侧图标按钮控制；悬浮窗隐藏后，可从主界面右上角的“悬浮窗”按钮或系统托盘重新打开。

点击标题栏的“吸附”图标，悬浮窗会选择距离当前位置最近的屏幕边缘并收成行情窄条。窄条保留当前主行情的名称、最新价和涨跌幅；鼠标移入立即展开，移出整个窗口 650ms 后自动收起，因此查行情时可见，不操作时不会长期遮挡桌面。macOS 使用 `NSTrackingArea + activeAlways` 接收原生进入和离开事件，不依赖 WebView 或应用焦点，切换到其他应用后仍能正常收起；只有原生 tracking area 安装失败时才会启用坐标轮询兜底。顶部、右侧、底部和左侧都可吸附；再次点击图标可取消吸附。拖动已经展开的吸附窗口会自动取消吸附，再按新的位置决定下一次停靠边缘。

### 自选行情

- 上证指数与自选行情共用交易时段刷新节奏。指数报价和分时走势独立容错：其中一路暂时不可用时保留另一路与最近缓存，并明确标注缓存状态。
- 右键单击顶部主行情卡，可在上证指数和当前自选股之间切换；选择股票后，上证指数会占据该股票原来的列表位置，避免股票重复或指数消失。列表中的指数卡只展示行情，左键不会改变已固定的主行情。聚焦顶部卡片后也可使用系统菜单键或 `Shift + F10` 打开选择菜单。
- 点击悬浮窗右上角 `+`，可按名称、代码或拼音首字母添加最多 8 只股票。
- A 股连续交易时段每 15 秒批量刷新一次；集合竞价阶段每 30 秒刷新；午休和收盘后停止自动请求。
- 个股行情卡显示最新价、涨跌额、涨跌幅、今开、最高、最低、成交额、换手率和当日分时走势。分时图包含价格线、均价线、昨收基准线与最新分钟时间；多只股票由后端并发批量预取，单只曲线失败不会阻塞其它行情。
- 点击股票会打开主窗口并自动进入该股票的个股分析。
- 每只自选股右侧有排序把手；拖到另一张卡片的上半部或下半部可调整前后顺序，聚焦把手后也可使用上下方向键。顺序会写入本地缓存，排在第一位的股票会显示在吸附窄条中。
- 也可以在主窗口完成个股分析后点击“加入悬浮窗”。自选列表保存在客户端本地，重启后仍会保留。
- 实时行情源暂时不可用时会保留最近本地快照并明确标注，不会一直停留在加载状态。

“今日机会”视图每 60 秒读取最新线上选股报告，展示候选数量、最高评分和前三只候选的最新价、涨跌幅及低吸区间。点击候选会唤起主窗口并打开对应股票的证据抽屉。

主窗口和悬浮窗的关闭动作都是“隐藏”，不会退出客户端。系统托盘提供“打开主界面”“显示 / 隐藏悬浮窗”和“退出”；只有选择退出或使用系统退出命令时才终止应用。

## 自动更新

- 主窗口启动 3 秒后静默检查一次，之后每 4 小时复查；悬浮窗不会重复发起请求。
- macOS 左上角应用菜单提供 `Check for Updates…`，Windows/Linux 的原生应用菜单也提供同一入口。手动检查会明确提示“已是最新版本”或错误原因。
- 发现更高的 SemVer 版本后，主窗口右上角出现“更新至 vX”按钮。点击后展示下载进度，签名验证和安装完成后按钮变为“重启完成更新”。Windows 安装器受平台限制可能在安装阶段自动退出客户端。
- 更新元数据来自 GitHub Releases 的 `latest.json`；安装包必须通过客户端内置公钥验证，私钥不得提交到仓库。

日常桌面构建不会创建 GitHub Release。面向 `main` 的 PR 或合入 `main` 的提交只要修改了 `desktop/`、`backend/`、`frontend/`、`src-tauri/`、桌面构建脚本、根依赖锁文件或桌面工作流，就会自动运行 `Build desktop client`，并把 macOS arm64/x64、Windows x64 和 Linux x64 安装包保存到该次 GitHub Actions 的 Artifacts。也可以从 Actions 页面手动运行这个 workflow。

发布新桌面版本：

1. 同步修改 `src-tauri/tauri.conf.json` 与 `src-tauri/Cargo.toml` 的版本号。
2. 在仓库 Secrets 中配置 `TAURI_SIGNING_PRIVATE_KEY`；有密码的私钥还需配置 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`。私钥文件权限应保持 `0600` 并另行安全备份。
3. 将版本提交合入 `main`，创建与配置完全一致的 tag，并推送：`git tag desktop-vX.Y.Z && git push origin desktop-vX.Y.Z`。
4. `Publish desktop release` 会先创建 draft，构建各平台签名安装包和聚合后的 `latest.json`；全部平台成功后才自动发布为 Latest，客户端随后会发现更新。任一平台失败时 release 保持 draft，不会向客户端分发不完整更新。

手动运行 `Publish desktop release` 只生成 draft，适合正式打 tag 前验证安装包；它不会自动发布为 Latest。

普通 `npm run desktop:build` 仍使用 `tauri.prod.conf.json`，不要求 updater 私钥。只有发布流水线或 `npm run desktop:release` 使用 `tauri.release.conf.json` 生成签名更新制品；本地验证无密码私钥时需显式设置 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD=''`。

已经安装的旧版必须本身包含 updater 才能自动升级，因此该能力从首次发布包含本节代码的版本开始生效。更早版本仍需手工安装一次新客户端。

## 数据与安全

- 默认生产客户端启动打包后的 FastAPI sidecar，API 只绑定本机回环地址。
- Web 通知设置接口继续使用 CSRF header + HttpOnly cookie 双提交校验。
- Tauri 自定义协议没有浏览器 cookie，同一接口改用受信任 Tauri origin + 短时签名 header；普通网页不能使用该例外。
- Tauri CSP 的 `connect-src` 放行本地回环地址和可选的 HTTPS 定制服务；公开构建不注入部署地址。
- 本地构建使用 ad-hoc 签名。正式对外分发时应把 `src-tauri/tauri.prod.conf.json` 和 `src-tauri/tauri.release.conf.json` 的签名身份替换为 Apple Developer ID，并完成 notarization。

## 测试

```bash
npm run test:api       # FastAPI/业务测试，含桌面 origin 鉴权
npm run test:web       # 前端单测 + Web 生产构建
npm run test:desktop   # Rust/Tauri 单测
npm run test           # 上述全部检查
```

发布前还必须执行一次 `npm run desktop:build`，并打开生成的安装包确认：

1. 安装包复制到 `/Applications` 后能被系统应用搜索找到，并能进入主工作台。
2. 客户端启动的本地 `/api/health` 返回 `ready`。
3. 页面路由可切换。
4. 关闭窗口后可从托盘恢复；从托盘退出后客户端进程结束。
5. 不安装 Python、不手工启动后端时，生产客户端仍能通过 sidecar 读取公开行情。
6. Web 的 `npm run dev` 和 `npm run build` 仍然独立可用。
7. 使用比当前客户端更高的测试版本发布 draft、确认 `latest.json` 的平台 URL 与签名完整，再发布 release；客户端右上角出现更新按钮并能完成重启升级。

## 代码复用规则

- 通用股票、量化、消息和设置能力放在 `frontend/src/features` 与 `frontend/src/lib`。
- 仅原生能力通过小型 desktop adapter 调用 `@tauri-apps/api`。
- 不在通用组件里直接依赖 Rust command；组件应通过可测试的 TypeScript 接口调用桌面能力。
- 悬浮框使用独立轻量路由，但复用现有 API client、格式化函数、股票类型和 QueryClient 配置。
