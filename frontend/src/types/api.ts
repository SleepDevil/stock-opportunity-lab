export type StockBoardCode = 'main' | 'startup' | 'star' | 'bse' | 'unknown';

export type TrendPoint = {
  日期: string;
  开盘?: number | null;
  收盘?: number | null;
  最高?: number | null;
  最低?: number | null;
};

export type IntradayPoint = {
  时间: string;
  股票代码: string;
  开盘?: number | null;
  收盘?: number | null;
  最高?: number | null;
  最低?: number | null;
  成交量?: number | null;
  成交额?: number | null;
  均价?: number | null;
};

export type IntradayResponse = {
  symbol: string;
  period: string;
  trade_date?: string | null;
  source: string;
  rows: IntradayPoint[];
};

export type Candidate = {
  排名: number;
  代码: string;
  名称: string;
  交易板块?: string;
  交易板块代码?: StockBoardCode | string;
  最新价: number;
  涨跌幅: number;
  成交额: number;
  换手率: number;
  量比: number;
  总市值: number;
  流通市值: number;
  '60日涨跌幅': number;
  score: number;
  机会标签: string;
  计划低吸价: number;
  计划买入上限: number;
  突破确认价: number;
  高开放弃价: number;
  止损参考价: number;
  第一止盈价: number;
  '单票仓位上限%': number;
  '单笔风险预算%': number;
  行业?: string;
  上市时间?: string;
  买入策略: string;
  走势点位?: TrendPoint[] | string | null;
};

export type BacktestRow = Candidate & {
  实际日期?: string;
  实际开盘?: number;
  实际最高?: number;
  实际最低?: number;
  实际收盘?: number;
  实际涨跌幅?: number;
  实际成交额?: number;
  实际换手率?: number;
  是否买入: boolean;
  买入方式: string;
  模拟买入价?: number | null;
  '收盘浮盈%'?: number | null;
  '盘中最大浮盈%'?: number | null;
  '盘中最大回撤%'?: number | null;
  盘中触及止损?: boolean | null;
  盘中触及止盈?: boolean | null;
  收盘站上计划上限?: boolean | null;
};

export type ScreenResponse = {
  trade_date: string;
  raw_count: number;
  filtered_count: number;
  board_excluded_count?: number;
  excluded_boards?: string[];
  candidates: Candidate[];
  report_paths: Record<string, string>;
  ai_payload: unknown;
  analysis: string;
};

export type BacktestResponse = {
  screen_date: string;
  actual_date: string;
  rows: BacktestRow[];
  summary: {
    candidate_count: number;
    bought_count: number;
    no_entry_count: number;
    entry_rate: number;
    win_rate: number;
    avg_close_return: number;
    median_close_return: number;
    avg_max_drawdown: number;
    best?: { code: string; name: string; return: number; entry_mode: string } | null;
    worst?: { code: string; name: string; return: number; entry_mode: string } | null;
  };
  report_paths: Record<string, string>;
  ai_payload: unknown;
  analysis: string;
};

export type AppConfig = {
  data_dir: string;
  screen: Record<string, unknown>;
  strategy: Record<string, unknown>;
};
