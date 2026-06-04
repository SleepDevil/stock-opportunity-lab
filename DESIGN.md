# Design

## Source of Truth
- Status: Active
- Last refreshed: 2026-06-03
- Primary product surfaces: 盘后机会雷达、策略回溯实验室、消息异动分析、板块资金与情绪总览、个股机会详情、策略配置。
- Evidence reviewed:
  - User goal: 网站需要从单页工具升级为能用于 Google Stitch 生成高质量设计图的投研产品 PRD。
  - Current implementation: [frontend/src/App.tsx](/Users/sleepdevil1/xigua-fe/stock-opportunity-lab/frontend/src/App.tsx), [frontend/src/styles.css](/Users/sleepdevil1/xigua-fe/stock-opportunity-lab/frontend/src/styles.css), [backend/app/services/screener.py](/Users/sleepdevil1/xigua-fe/stock-opportunity-lab/backend/app/services/screener.py), [backend/app/services/backtest.py](/Users/sleepdevil1/xigua-fe/stock-opportunity-lab/backend/app/services/backtest.py), [README.md](/Users/sleepdevil1/xigua-fe/stock-opportunity-lab/README.md).
  - Stitch prompts/review: [docs/prompts/google-stitch-redesign-v2.md](/Users/sleepdevil1/xigua-fe/stock-opportunity-lab/docs/prompts/google-stitch-redesign-v2.md), [docs/prompts/google-stitch-polish-v3.md](/Users/sleepdevil1/xigua-fe/stock-opportunity-lab/docs/prompts/google-stitch-polish-v3.md), [docs/design-tree/stitch-visual-review-2026-06-03.md](/Users/sleepdevil1/xigua-fe/stock-opportunity-lab/docs/design-tree/stitch-visual-review-2026-06-03.md).
  - Current constraints: React + Vite + TypeScript frontend, FastAPI + pandas + AkShare backend, local CSV/JSON/Markdown cache, no broker connection, no auto-trading.

## Brand
- Personality: 专业、克制、敏捷、证据优先；像一个个人量化投研驾驶舱，而不是财经资讯门户。
- Trust signals: 明确交易日期、数据源状态、缓存时间、策略版本、回测样本范围、失败原因、风险边界。
- Avoid: 营销式首屏、夸张盈利暗示、全屏霓虹大屏、单色蓝紫渐变、无依据的买入建议、隐藏筛选条件。

## Product Goals
- Goals:
  - 每日盘后自动从 A 股市场筛出候选机会，并给出次日计划价格区间。
  - 用历史数据验证策略在不同市场阶段是否有效，支持持续优化。
  - 对严重异动股票补充消息面解释，识别“消息误杀”或真实风险。
  - 直观看出板块资金强弱、市场情绪、大盘环境是否适合开仓。
- Non-goals:
  - 不连接券商、不保存交易凭证、不自动下单。
  - 不承诺收益，不输出无依据的“必买”结论。
  - V1 不开放复杂拖拽式策略编辑器，先使用写死策略和只读参数展示。
- Success signals:
  - 用户 3 分钟内完成当天盘后机会扫描。
  - 用户能看清每只候选股为什么入选、什么价格买、什么条件放弃。
  - 用户能选择历史区间并看到策略胜率、回撤、触发率、分市场环境表现。
  - 用户能从消息异动和板块资金判断今天是否适合进攻、等待或防守。

## Personas and Jobs
- Primary personas:
  - 个人 A 股投资者：懂基础技术指标，希望用规则减少情绪化决策。
  - 量化学习者：想验证固定策略在历史市场里的真实表现。
  - 盘后复盘用户：每天收盘后需要快速得到明天的观察列表。
- User jobs:
  - “今天哪些股票值得加入明天观察？”
  - “这个策略长期到底有没有用，在哪些行情里失效？”
  - “某只股票突然跌停/涨停，是否属于消息误杀、板块带动或基本面风险？”
  - “今天市场和板块情绪适不适合提高仓位？”
- Key contexts of use:
  - A 股收盘后桌面使用为主。
  - 数据源偶发失败，需要展示缓存、重试和降级状态。
  - 用户会把结果与券商软件、同花顺、新闻源交叉查看。

## Information Architecture
- Primary navigation:
  - 今日机会
  - 回测实验室
  - 消息异动
  - 板块资金
  - 策略设置
- Core routes/screens:
  - Dashboard: 今日市场环境、盘后扫描、候选池、风险提示。
  - Candidate Detail: 个股量价证据、价格计划、消息解释、板块关系、历史同类样本。
  - Backtest Lab: 策略版本、日期区间、绩效曲线、交易明细、参数对比。
  - News & Catalyst: 异动榜、消息标签、事件时间线、机会/风险归因。
  - Sector Flow: 板块热力图、资金流入流出、强弱轮动、市场情绪温度计。
  - Strategy Settings: 当前写死策略的只读展示，后续升级为可配置策略。
- Content hierarchy:
  - 顶部：交易日期、数据状态、市场情绪总分、主要操作。
  - 中部：机会列表与板块/消息联动。
  - 右侧或下方：策略解释、风险条件、报告输出。
  - 深层：详情页和回测实验室承载复杂分析。

## Design Principles
- Principle 1: 先判断市场环境，再判断个股机会。
- Principle 2: 每个候选必须同时展示入选理由、买入计划、放弃条件、风险边界。
- Principle 3: 回测结果要比单日推荐更重要，避免“看起来聪明”的随机分析。
- Principle 4: 消息面只做证据归因，不编造新闻或基本面结论。
- Tradeoffs:
  - 优先桌面密度和扫描效率，移动端只保证可查看核心结果。
  - 优先真实数据可解释性，少用装饰型图表。
  - V1 用固定策略换稳定交付，策略编辑器后置。

## Visual Language
- Color:
  - 主背景：冷白/浅灰工作台。
  - 主色：深墨蓝用于导航和重点操作。
  - 辅色：青绿色表示资金流入/机会，琥珀表示观察/波动，克制红色表示风险。
  - 不使用大面积红绿对撞；涨跌颜色必须配文字标签。
- Typography:
  - 系统 sans-serif；数字使用 tabular nums。
  - 控制台和表格使用紧凑字号，详情标题使用中等层级，不做夸张 hero。
- Spacing/layout rhythm:
  - 桌面以 12px 网格和 8px 半径为基础。
  - 数据表格密度高但留足行内分组，重要指标用固定宽度数字列。
- Shape/radius/elevation:
  - 卡片半径不超过 8px。
  - 页面区块使用全宽工作区和轻边框，不做卡片套卡片。
  - 阴影极轻，主要依赖边框和层级。
- Motion:
  - 仅用于扫描、回测、刷新状态。
  - 不用闪烁行情动画，不用持续滚动 ticker。
- Imagery/iconography:
  - 使用 lucide 风格线性图标。
  - 不使用股票照片、抽象金融插画或装饰性渐变图。

## Stitch Visual Review
- Latest reviewed version: Google Stitch V3, generated 2026-06-03.
- Keep:
  - 冷白工作台、深墨蓝窄导航、克制红绿风险语义。
  - 市场状态带、今日决策栈、事件调查台、板块资金地图这些产品化命名。
  - 数字列对齐、轻边框、高密度扫描的投研终端气质。
- Do not copy directly:
  - 首页候选区仍然偏普通表格，实际实现要做成“机会条”：排名/评分、股票身份、K 线、价格计划、证据状态横向组合。
  - 右侧栏不要只是后台卡片堆叠，要作为可操作的决策栈，支持跳转到消息、板块、回测证据。
  - 视觉不要继续加深色大屏风格；深色只用于局部高密度分析页或强调区。

## Components
- Existing components to reuse:
  - KPI strip
  - Candidate table
  - Backtest table
  - Analysis panel
  - Config panel
- New/changed components:
  - App shell with left navigation and command bar
  - Market regime summary
  - Sector heatmap and fund-flow ranking
  - News catalyst timeline
  - Candidate detail drawer/page
  - Strategy version selector
  - Backtest equity curve and distribution chart
  - Data-source status banner
  - Opportunity/risk explanation cards
- Variants and states:
  - Loading, stale cache, partial data, source degraded, empty result, error, success, disabled, high-risk warning.
- Token/component ownership:
  - Keep CSS variables in `frontend/src/styles.css` until a larger component system is justified.

## Accessibility
- Target standard: Practical WCAG AA for contrast, keyboard reachability, form labels, table headers.
- Keyboard/focus behavior: Navigation, filters, buttons, table row detail, copy/export all reachable by keyboard.
- Contrast/readability: Color cannot be the only signal for rise/fall, risk, or opportunity.
- Screen-reader semantics: Tables use headers; charts need text summary; loading/errors are textual.
- Reduced motion and sensory considerations: All motion optional and nonessential.

## Responsive Behavior
- Supported breakpoints/devices:
  - Desktop first: 1280px and wider.
  - Tablet: 768px to 1279px with stacked panels.
  - Mobile: core result reading only, horizontal table scroll allowed.
- Layout adaptations:
  - Desktop: left nav + top command bar + main dashboard grid.
  - Tablet: nav becomes top tabs; charts stack above tables.
  - Mobile: show summary cards first, tables become horizontal scroll.
- Touch/hover differences:
  - Hover tooltips must have visible equivalents.
  - Detail drawers need explicit close buttons and large hit targets.

## Interaction States
- Loading:
  - Show operation label: 扫描中、回测中、同步消息中、刷新板块资金中。
  - Keep previous successful result visible with “正在刷新” state.
- Empty:
  - Explain whether no stocks passed filters, missing historical report, or data source unavailable.
- Error:
  - Show source-level diagnosis and retry option, not stack traces.
- Success:
  - Show generated report path, strategy version, data timestamp.
- Disabled:
  - Duplicate operation buttons disabled while same task running.
- Offline/slow network:
  - Use cached data when available and mark it clearly as stale.

## Content Voice
- Tone: 准确、克制、风险意识强。
- Terminology:
  - Use: 候选、观察池、计划区间、触发买入、高开放弃、止损参考、消息误杀、板块强度、市场情绪、策略版本。
  - Avoid: 神股、稳赚、抄底神器、必买、暴富、内幕。
- Microcopy rules:
  - 所有日期使用绝对日期。
  - 所有推荐都要带“不构成投资建议”语义。
  - 分析句式必须引用数据证据或明确标记为假设。

## Implementation Constraints
- Framework/styling system: React 19, Vite, TypeScript, Mantine, lucide-react, CSS custom properties.
- Backend/data: FastAPI, pandas, AkShare, EastMoney/curl_cffi fallback, local CSV/JSON/Markdown cache.
- Design-token constraints: Use Mantine for mature controls and overlays, but keep product-defining surfaces such as opportunity strips and decision stack in repo CSS.
- Performance constraints:
  - Long-running scan/backtest must show progress or staged status.
  - Backtest date-range jobs should be asynchronous in later implementation.
- Compatibility constraints:
  - Local desktop browser first.
  - No broker credentials and no production trading automation.
- Test/screenshot expectations:
  - Backend pytest, frontend production build.
  - Browser smoke check for Dashboard, Backtest Lab, News Catalyst, Sector Flow once implemented.

## Open Questions
- [ ] 消息源优先接入哪一类：AkShare 新闻、财联社/东方财富公开资讯、RSS、手动导入？Owner: user. Impact: 消息面分析可信度。
- [ ] 板块资金使用哪个分类体系：申万行业、东方财富概念、同花顺概念、自定义主题？Owner: user. Impact: 板块热力图和个股归因。
- [ ] 回测粒度是否只用日线，还是需要分钟线验证计划价触发？Owner: user. Impact: 回测可信度与数据成本。
- [ ] 是否需要推送到飞书/微信/邮件？Owner: user. Impact: 异动提醒和定时任务。
