# Stock Opportunity Lab

一个本地 Web 应用：用 AkShare 在盘后筛选 A 股机会，生成第二天买入计划，并把前一日计划和次日实际走势做回测对比。

## 技术栈

- Frontend: React 19, Vite, TypeScript, Mantine, lucide-react
- Backend: FastAPI, pandas, AkShare
- Storage: 本地 CSV/JSON/Markdown 缓存，目录在 `data/`

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
5. AI/规则解释区会展示受控分析：只能使用系统传入的指标和回测结果，不编造新闻或基本面。

## 产品与设计文档

- 产品 PRD：`docs/prd/stock-opportunity-lab-prd.md`
- Google Stitch 生成提示词：`docs/prompts/google-stitch-stock-opportunity-lab.md`
- 设计结构树：`docs/design-tree/stock-opportunity-lab.md`
- 设计契约：`DESIGN.md`

## 注意

AkShare 当前全市场快照适合每天盘后缓存。要严格回放某个历史日的全市场筛选，必须当天已经有 `data/raw/spot_YYYYMMDD.csv` 或 `data/reports/screen_YYYYMMDD.csv`。否则历史全市场市值和量比无法完全还原。

## 验证

```bash
npm run test
```
