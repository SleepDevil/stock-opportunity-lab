# Stock Opportunity Lab Design Tree

- Status: draft
- Last refreshed: 2026-06-03
- design_target_type: system
- Parent: none
- Owner: Stock Opportunity Lab product/design planning

## Problem

当前网站已经能完成单日盘后扫描和次日回测，但产品目标还不清晰，UI 也更像工程调试台而不是投研决策工作台。需要把它扩展成一个围绕“机会发现、策略验证、消息归因、板块情绪”的 A 股个人投研网站，并生成足够结构化的 PRD 给 Google Stitch 产出更好的设计图。

## Scope

Included:
- 每日盘后固定策略推荐股票。
- 历史回溯与策略有效性验证。
- 消息面异动分析和机会/风险归因。
- 板块资金流入流出、强弱、情绪和大盘环境判断。
- 面向 Stitch 的多屏 UI 生成说明。

Excluded:
- 自动交易、券商账号接入、真实下单。
- V1 的自由拖拽式策略编辑器。
- 无来源的新闻编造或基本面断言。

## Assumptions

- 产品以桌面端为主。
- V1 使用写死策略，后续再支持自定义策略。
- 数据源允许降级和缓存，但所有降级必须可见。
- 分析输出必须以数据证据、新闻来源或明确假设为基础。

## Design Tree

```
design_tree
├── 1. Product position ✓
│   ├── 1.1 Personal A-share research cockpit
│   └── 1.2 Evidence-first, no auto-trading
├── 2. Core flows [DRAFT]
│   ├── 2.1 Daily after-market opportunity scan
│   ├── 2.2 Candidate detail and next-day plan
│   ├── 2.3 Strategy backtest and optimization
│   ├── 2.4 News catalyst review
│   └── 2.5 Sector fund-flow and sentiment review
├── 3. Core objects [DRAFT]
│   ├── 3.1 Candidate stock
│   ├── 3.2 Strategy version
│   ├── 3.3 Backtest run
│   ├── 3.4 News catalyst
│   └── 3.5 Sector regime
├── 4. Information architecture [DRAFT]
│   ├── 4.1 Today Opportunities
│   ├── 4.2 Backtest Lab
│   ├── 4.3 News & Catalyst
│   ├── 4.4 Sector Flow
│   └── 4.5 Strategy Settings
├── 5. Data dependencies [RESEARCH]
│   ├── 5.1 AkShare market data ✓
│   ├── 5.2 EastMoney fallback ✓
│   ├── 5.3 News source [OPEN]
│   └── 5.4 Sector taxonomy [OPEN]
├── 6. UI design direction [DRAFT]
│   ├── 6.1 Dense desktop research cockpit
│   ├── 6.2 Calm neutral palette with risk accents
│   ├── 6.3 Tables plus heatmaps, timelines, curves
│   └── 6.4 No marketing hero or decorative finance page
└── 7. Decision nodes [DECISION]
    ├── 7.1 News source priority
    ├── 7.2 Sector taxonomy
    ├── 7.3 Backtest granularity
    └── 7.4 Push notification channel
```

## Open Branches

- 5.3 News source: needs source availability and citation policy.
- 5.4 Sector taxonomy: needs product choice between industry and concept classification.
- 7.3 Backtest granularity: daily K line is cheaper; minute-level data makes entry trigger more trustworthy.
- 7.4 Push channel: affects backend scheduling and account integration.

## Decision Nodes

| Node | Options | Recommended default |
| --- | --- | --- |
| News source priority | AkShare/public finance news, manual import, paid feeds later | Start with public sources plus citation links |
| Sector taxonomy | 申万行业, 东方财富行业/概念, 同花顺概念 | Start with 东方财富/AKShare-accessible sectors |
| Backtest granularity | 日线, 分钟线, 混合 | V1 日线, V2 分钟线验证触发 |
| Push channel | None, Feishu, email, WeChat | V1 in-app alerts, V2 Feishu/email |

## External Dependencies

- Google Stitch: [RESEARCH] used only as a design-generation target. Official Google material says Stitch can generate UI designs and frontend code from natural-language prompts and supports richer flows plus design-system context.
- AkShare: ✓ already installed and used for market data.
- EastMoney endpoints: ✓ already used with `curl_cffi` fallback where available.
- Public news/catalyst sources: [OPEN] source reliability and citation rules still need validation.
- Sector fund flow sources: [OPEN] endpoint choice still needs validation.

## Status

The initial design tree is stable enough for PRD and Stitch prompt generation. It is intentionally draft-level because news sources, sector taxonomy, and backtest granularity still need product decisions.
