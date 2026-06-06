import type {
  AppConfig,
  LearningSummary,
  NotificationSettings,
  ScreenReportsResponse,
  StrategyExperiment,
  StrategyOptimizationResponse,
  WechatKnowledgeResponse
} from '../types/api';

const unavailableMessage =
  '当前是 GitHub Pages 静态镜像：页面长期可访问，但不会连接后端、数据库或行情采集。完整扫描、写入和通知请使用 Vercel/Docker 后端。';

const screenConfig = {
  max_candidates: 30,
  min_price: 3,
  max_price: 300,
  min_amount: 200_000_000,
  min_turnover: 3,
  max_turnover: 15,
  min_volume_ratio: 1.2,
  min_float_market_cap: 3_000_000_000,
  max_float_market_cap: 50_000_000_000,
  min_total_market_cap: 5_000_000_000,
  max_total_market_cap: 100_000_000_000,
  min_pct_change: -6,
  max_pct_change: 9.5,
  exclude_name_regex: 'ST|退|N|C',
  score_weights: {
    amount: 0.25,
    volume_ratio: 0.2,
    turnover: 0.2,
    pct_change: 0.15,
    market_cap_fit: 0.1,
    sixty_day_strength: 0.1
  }
};

const strategyConfig = {
  entry_discount: 0.012,
  entry_premium: 0.012,
  breakout_premium: 0.026,
  avoid_gap_up: 0.045,
  stop_loss: 0.055,
  take_profit: 0.085,
  max_single_position_pct: 12,
  risk_per_trade_pct: 1
};

const now = () => new Date().toISOString();

const config: AppConfig = {
  data_dir: 'static-github-pages',
  screen: {
    ...screenConfig,
    mode: 'static-mirror',
    capability_note: unavailableMessage
  },
  strategy: {
    ...strategyConfig,
    mode: 'static-mirror'
  }
};

const learningSummary: LearningSummary = {
  total_cases: 0,
  buy_cases: 0,
  winning_buys: 0,
  losing_buys: 0,
  missed_cases: 0,
  buy_win_rate: 0,
  avg_buy_return: 0,
  avg_max_drawdown: 0,
  user_feedback_count: 0,
  top_failure_reasons: [],
  top_success_reasons: [],
  strategy_insights: {
    target_win_rate: 80,
    win_rate_gap: 80,
    sample_status: 'static',
    recommendations: [unavailableMessage]
  },
  recent_records: [],
  updated_at: null
};

function staticExperiment(): StrategyExperiment {
  const createdAt = now();
  return {
    id: 'static-github-pages',
    status: 'static',
    target_win_rate: 80,
    current_metrics: {
      total_cases: 0,
      buy_cases: 0,
      buy_win_rate: 0,
      avg_buy_return: 0,
      avg_max_drawdown: 0
    },
    current_strategy: strategyConfig,
    proposed_strategy: strategyConfig,
    parameter_changes: [],
    experiment_plan: [
      {
        name: '连接完整后端后开始记录样本',
        status: 'static',
        metric: 'buy_win_rate',
        notes: unavailableMessage
      }
    ],
    disclaimer: unavailableMessage,
    created_at: createdAt,
    updated_at: createdAt,
    outcomes: []
  };
}

function strategyOptimization(): StrategyOptimizationResponse {
  const experiment = staticExperiment();
  return {
    target_win_rate: 80,
    current_metrics: experiment.current_metrics,
    current_strategy: strategyConfig,
    proposed_strategy: strategyConfig,
    parameter_changes: [],
    experiment_plan: experiment.experiment_plan,
    experiment,
    experiment_history: [],
    disclaimer: unavailableMessage
  };
}

const wechatKnowledge: WechatKnowledgeResponse = {
  subscriptions: [],
  articles: [],
  capability_note: unavailableMessage
};

const screenReports: ScreenReportsResponse = {
  dates: [],
  latest: null
};

function notificationSettings(): NotificationSettings {
  return {
    user_email: null,
    board_exclusion_enabled: true,
    excluded_boards: ['startup', 'star', 'bse']
  };
}

function normalizedPath(path: string): string {
  try {
    return new URL(path, 'https://static.stock-lab.local').pathname;
  } catch {
    return path.split('?')[0] || path;
  }
}

export function isStaticMode(): boolean {
  return import.meta.env.VITE_STOCK_LAB_STATIC_MODE === 'true';
}

export async function staticRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase();
  const route = normalizedPath(path);
  if (method !== 'GET') {
    throw new Error(unavailableMessage);
  }

  const payloads: Record<string, unknown> = {
    '/api/client-auth': { csrf_token: 'static-github-pages' },
    '/api/config': config,
    '/api/learning-summary': learningSummary,
    '/api/strategy-optimization': strategyOptimization(),
    '/api/wechat-knowledge': wechatKnowledge,
    '/api/screen-reports': screenReports,
    '/api/notification-settings': notificationSettings()
  };

  if (route in payloads) {
    return payloads[route] as T;
  }

  throw new Error(unavailableMessage);
}
