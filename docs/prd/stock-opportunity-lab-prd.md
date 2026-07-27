# Stock Opportunity Lab PRD

- Status: Draft for design generation
- Last updated: 2026-06-03
- Product type: Local web research cockpit for A-share opportunity screening
- Primary audience: Individual A-share investor using data-driven after-market review
- Design target: Google Stitch high-fidelity desktop web app mockup

## 1. Background

Stock Opportunity Lab 当前是一个本地 Web 工具，已经具备盘后扫描、候选表、次日价格计划、回测表和受控分析。但产品还停留在“工程工具”阶段：页面信息结构单薄，功能边界不够明确，缺少消息面、板块资金、历史策略有效性这三类投研核心视角。

本 PRD 的目标是把网站定义为一个个人 A 股投研工作台：每天盘后先判断大盘和板块环境，再筛选个股机会，最后用历史回测和消息归因约束交易冲动。

## 2. Product Vision

让用户每天盘后用一套固定、可验证、可迭代的流程回答四个问题：

1. 今天市场环境适合进攻、观察还是防守？
2. 哪些股票符合策略，明天应该在什么价格区间观察？
3. 这个策略在历史上到底有没有用，在哪些行情里失效？
4. 某些异动股票是消息误杀、板块拖累，还是自身风险？

## 3. Goals and Non-goals

### Goals

- 每日盘后基于当天全市场数据生成股票候选清单。
- 为每只候选股生成次日计划区间、高开放弃价、止损参考价、仓位和风险预算。
- 支持历史回溯，展示策略在日期区间、市场环境和板块维度的表现。
- 支持消息面分析，尤其识别严重异动中的机会型误杀和真实风险。
- 支持板块资金流入流出和市场情绪总览，帮助判断策略是否应该开仓。
- 输出可解释、可追溯、可导出的报告。

### Non-goals

- 不连接券商账户，不自动下单。
- 不承诺收益，不给无风险买入建议。
- V1 不做复杂策略编辑器，只展示固定策略和必要参数。
- 不生成无来源的新闻分析。

## 4. User Personas

### Persona A: 盘后复盘型个人投资者

- 使用场景：每天 15:00 后复盘，晚上决定次日观察列表。
- 核心诉求：快速看到机会、风险、价格计划，不想翻多个软件。
- 成功标准：能在 3 分钟内形成明日观察池。

### Persona B: 策略验证型用户

- 使用场景：想知道一个策略到底有没有历史优势。
- 核心诉求：看胜率、触发率、回撤、失效行情，而不是只看单日推荐。
- 成功标准：能选择区间并判断策略是否值得继续优化。

### Persona C: 消息异动捕捉者

- 使用场景：看到跌停、炸板、大成交异动后，需要判断是否是机会。
- 核心诉求：把价格异动、消息事件、板块环境和历史反应放在一起看。
- 成功标准：能区分“消息误杀机会”和“基本面风险”。

## 5. Current State

已实现：
- 盘后扫描接口和页面按钮。
- 固定策略筛选：成交额、换手率、量比、市值、涨跌幅、60 日强度。
- 候选股表：排名、分数、成交额、换手率、计划价格。
- 次日回测：触发率、胜率、平均浮盈、回撤、交易明细。
- 本地缓存和 Markdown/CSV/JSON 报告。

主要不足：
- 缺少清晰导航和产品模块。
- Dashboard 不能先判断市场环境。
- 历史回溯只是一日对比，不是完整策略实验室。
- 消息面分析还只是规则解释，没有新闻/事件时间线。
- 板块强弱和资金流完全缺失。
- UI 视觉层级偏工具化，缺少设计完整性。

## 6. Proposed Product Structure

### 6.1 今日机会

目的：每日盘后生成次日观察池。

核心内容：
- 数据状态条：交易日、数据源、缓存状态、策略版本、最近刷新时间。
- 市场环境摘要：大盘涨跌、上涨/下跌家数、成交额、涨停/跌停数量、情绪评分。
- 板块强弱摘要：Top inflow sectors, Top outflow sectors, strongest themes.
- 盘后扫描操作：日期、候选数量、刷新数据、补行业信息。
- 候选股列表：分数、机会标签、价格计划、风险条件、消息状态、板块归属。
- 明日行动计划：低吸区间、突破确认、高开放弃、止损参考、仓位上限。

关键交互：
- 点击候选股打开详情页或右侧抽屉。
- 可以按分数、成交额、换手率、量比、板块、消息异动筛选。
- 一键导出当天报告。

### 6.2 个股机会详情

目的：解释“为什么是这只股，以及什么情况下放弃”。

核心内容：
- Header: 股票名称、代码、行业/概念、机会评分、风险等级。
- 量价证据：成交额、换手率、量比、涨跌幅、市值、60 日强度。
- 价格计划：次日低吸区间、买入上限、突破确认、高开放弃、止损、第一止盈。
- 消息/事件：相关新闻、公告、舆情摘要、异动解释。
- 板块关系：所属板块强度、资金流、同板块候选排名。
- 历史同类样本：相似量价结构后 1/3/5 日表现。

关键交互：
- 标签化解释：高成交额、明显放量、消息误杀、板块共振、风险公告。
- 复制该股分析 Payload。
- 标记为“明日重点观察”。

### 6.3 回测实验室

目的：判断策略是否有效，而不是只看单日结果。

核心内容：
- 策略版本：当前固定策略 V1，参数只读展示。
- 区间选择：开始日期、结束日期、回测频率、候选 Top N。
- 核心绩效：触发率、胜率、平均收益、中位收益、最大回撤、盈亏比、样本数。
- 绩效图：权益曲线、月度热力图、收益分布、回撤曲线。
- 归因拆解：按市场环境、板块、成交额分位、换手率分位、量比分位拆分。
- 交易明细：每次候选、买入方式、模拟买入价、收盘浮盈、最大回撤、失败原因。

关键交互：
- 对比不同日期范围。
- 对比不同策略版本。
- 点击某次失败样本查看当日市场和消息背景。

### 6.4 消息异动

目的：对严重异动股票做消息归因，识别误杀机会。

示例场景：
- 东山精密 2026-06-01 跌停，如果消息面没有指向公司核心基本面恶化，而更像外部事件、短期情绪或市场误读，系统应把它标记为“疑似消息误杀”，并在 2026-06-02、2026-06-03 的走势中持续复盘验证。

核心内容：
- 异动榜：跌停、涨停、放量长阴、炸板、跳空低开、异常成交额。
- 新闻/公告时间线：事件时间、来源、摘要、影响方向。
- 归因标签：消息误杀、基本面风险、行业拖累、资金兑现、板块共振。
- 机会评分：是否值得观察、需要什么确认信号。
- 推送规则：严重异动且满足机会条件时推送。

关键交互：
- 用户可筛选“跌停但基本面未明显恶化”的候选。
- 支持查看事件前后 3 日价格走势。
- 支持加入观察池并在后续交易日复盘。

### 6.5 板块资金

目的：判断市场主线、情绪和策略适用环境。

核心内容：
- 市场温度计：进攻/观察/防守三态。
- 板块热力图：资金流入、涨幅、成交额、涨停家数、候选数量。
- 资金流排行：净流入 Top、净流出 Top、持续流入、突然转弱。
- 风格轮动：小盘/中盘/大盘、成长/周期/消费、防守/进攻。
- 个股联动：候选股所属板块是否有资金共振。

关键交互：
- 点击板块查看板块内候选股。
- 按资金流、涨幅、成交额、候选数量排序。
- 和今日机会列表联动过滤。

### 6.6 策略设置

目的：V1 展示固定策略，后续支持自定义。

V1 内容：
- 固定策略说明。
- 筛选条件：最低成交额、换手率区间、量比、市值、涨跌幅、排除 ST/退市。
- 打分权重：成交额、量比、换手率、涨跌幅、市值适配、60 日强度。
- 买入计划规则：低吸折扣、上限、突破确认、高开放弃、止损、止盈、仓位。
- 策略版本号和更新时间。

V2 方向：
- 可编辑参数。
- 保存策略版本。
- 回测对比不同策略版本。

## 7. Information Architecture

Primary navigation:
- 今日机会
- 回测实验室
- 消息异动
- 板块资金
- 策略设置

Dashboard first screen:
- Top command bar: date, refresh, strategy version, data source status.
- Left/main: market regime + candidate list.
- Right rail: sector flow, news alerts, selected candidate plan.
- Bottom: latest backtest summary and generated reports.

## 8. Functional Requirements

### FR1 Daily after-market scan

- User can select a trade date and run scan.
- System fetches full-market data or loads local cache.
- System applies fixed strategy filters and ranking.
- System outputs candidate list and next-day price plan.
- System persists CSV/JSON/Markdown report.

Acceptance criteria:
- Candidate rows include score, price plan, opportunity tags and risk fields.
- UI shows raw sample count, filtered count, candidate count and average score.
- Failed data source shows degraded status and retry option.

### FR2 Historical backtest

- User can select date range and strategy version.
- System replays historical scans where data exists.
- System calculates trigger rate, win rate, average return, median return, max drawdown and sample count.
- System supports viewing individual trades and failure reasons.

Acceptance criteria:
- Backtest result includes summary KPIs, chart-ready series and trade details.
- Missing data is reported per date, not hidden.
- Strategy version is persisted with each backtest run.

### FR3 News catalyst analysis

- System identifies abnormal moves: limit down/up, high-volume drop, gap down, long upper shadow, abnormal turnover.
- System associates news/announcements/events with affected stocks.
- System labels event type and confidence.
- System highlights “possible overreaction” opportunities with required confirmation conditions.

Acceptance criteria:
- Every news analysis item includes source, timestamp, summary and confidence.
- If no reliable source exists, UI says “消息源不足”, not invented analysis.
- Push/alert candidate includes why it matters and what would invalidate it.

### FR4 Sector fund-flow and sentiment

- System shows sector inflow/outflow ranking.
- System shows market regime score.
- System links sector strength to candidate stocks.
- System warns when market environment is hostile to the strategy.

Acceptance criteria:
- Sector panel includes inflow, outflow, breadth, momentum and candidate count.
- Candidate detail shows whether its sector is confirming or contradicting the stock signal.
- Dashboard has a clear market state: 进攻、观察 or 防守.

### FR5 Reports and explainability

- System generates reports for scan, backtest and catalyst review.
- AI/rule explanation uses only supplied data and cited news.
- User can copy structured analysis payload.

Acceptance criteria:
- Every report includes date, strategy version, data source status and disclaimer.
- Explanation cites relevant metrics or event sources.

## 9. Data Requirements

Existing data:
- Full-market spot snapshot.
- Daily historical K line or snapshot-derived OHLC.
- Candidate reports.
- Backtest reports.

New data needed:
- Sector fund flow by date.
- Market breadth and sentiment metrics.
- News/announcement/event items with source URLs.
- Strategy version metadata.
- Historical scan index for date-range backtesting.

Core entities:

| Entity | Key fields |
| --- | --- |
| CandidateStock | date, code, name, score, tags, price plan, risk limits |
| StrategyVersion | id, name, filters, weights, buy-plan rules, created_at |
| BacktestRun | strategy_id, start_date, end_date, metrics, trades |
| NewsCatalyst | code, event_time, source, summary, tags, confidence |
| SectorRegime | date, sector_name, inflow, outflow, breadth, momentum |
| MarketRegime | date, score, state, breadth, turnover, limit_up/down |

## 10. UX Requirements

- Desktop dashboard must feel like a professional work tool, not a marketing page.
- First screen must show market condition, scan action, candidate list and alert summary.
- Tables can be dense but must be scannable.
- Every chart must have a text summary.
- Risk signals must use both color and label.
- Long tasks must keep previous results visible.
- Empty/error states must explain the next action.

## 11. Visual Direction for Google Stitch

Design style:
- Calm professional quant research cockpit.
- Light neutral background with subtle borders.
- Dark navy navigation, teal/amber/red accents.
- Dense data tables, heatmaps, compact KPI strips, timelines and equity curves.
- No decorative finance hero, no stock photos, no giant gradient banner.

Key screens to generate:
1. Dashboard / 今日机会
2. Candidate detail / 个股机会详情
3. Backtest Lab / 回测实验室
4. News & Catalyst / 消息异动
5. Sector Flow / 板块资金
6. Strategy Settings / 策略设置

## 12. Risks

- Historical data availability may be incomplete if daily snapshots were not cached.
- News source reliability can make or break catalyst analysis.
- Minute-level trigger validation may be needed for accurate backtesting.
- UI could become too dense if all modules are placed on one screen.
- User may over-trust generated explanations unless disclaimers and evidence boundaries are visible.

## 13. Phasing

### V1: Better product shell and fixed strategy workflow
- New navigation and dashboard IA.
- Existing scan/backtest polished into coherent UI.
- Strategy version display.
- Data source status and report center.

### V1.5: Backtest Lab
- Date-range backtest.
- Equity curve, drawdown, returns distribution.
- Trade detail and failure reason drilldown.

### V2: News Catalyst
- Abnormal move detector.
- News/announcement timeline.
- Mispricing/overreaction labels.
- In-app alert center.

### V3: Sector Flow
- Sector inflow/outflow dashboard.
- Market regime score.
- Candidate-sector linkage.

### V4: Strategy customization
- Editable parameters.
- Saved strategy versions.
- Strategy comparison and optimization notes.

## 14. Open Questions

- Which news source should be authoritative for V2?
- Which sector taxonomy should be used first?
- Should backtest use only daily K line in V1, or add minute-level validation quickly?
- What push channel matters most: in-app, Feishu, email, WeChat?
- Should Stitch generate only desktop first, or also mobile/tablet variants now?
