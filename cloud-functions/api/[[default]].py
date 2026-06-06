from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse


DATA_DIR = Path(os.getenv("STOCK_LAB_DATA_DIR") or "/tmp/stock-opportunity-lab")


@dataclass
class ScreenConfig:
    max_candidates: int = 30
    min_price: float = 3.0
    max_price: float = 300.0
    min_amount: float = 200_000_000.0
    min_turnover: float = 3.0
    max_turnover: float = 15.0
    min_volume_ratio: float = 1.2
    min_float_market_cap: float = 3_000_000_000.0
    max_float_market_cap: float = 50_000_000_000.0
    min_total_market_cap: float = 5_000_000_000.0
    max_total_market_cap: float = 100_000_000_000.0
    min_pct_change: float = -6.0
    max_pct_change: float = 9.5
    exclude_name_regex: str = "ST|退|N|C"
    score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "amount": 0.25,
            "volume_ratio": 0.20,
            "turnover": 0.20,
            "pct_change": 0.15,
            "market_cap_fit": 0.10,
            "sixty_day_strength": 0.10,
        }
    )


@dataclass
class StrategyConfig:
    entry_discount: float = 0.012
    entry_premium: float = 0.012
    breakout_premium: float = 0.026
    avoid_gap_up: float = 0.045
    stop_loss: float = 0.055
    take_profit: float = 0.085
    max_single_position_pct: float = 12.0
    risk_per_trade_pct: float = 1.0


SCREEN = ScreenConfig()
STRATEGY = StrategyConfig()


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self._json({"ok": True}, headers={"Allow": "GET,POST,PUT,OPTIONS"})

    def do_GET(self):
        path = api_path(self.path)
        if path in ("", "/", "/health"):
            self._json({"ok": True, "message": "ready"})
            return
        if path == "/config":
            self._json(public_config())
            return
        if path == "/client-auth":
            self._json({"csrf_token": "edgeone-light-backend"})
            return
        if path == "/learning-summary":
            self._json(empty_learning_summary())
            return
        if path == "/strategy-optimization":
            self._json(strategy_optimization())
            return
        if path == "/wechat-knowledge":
            self._json(
                {
                    "subscriptions": [],
                    "articles": [],
                    "capability_note": "EdgeOne 当前部署为轻后端；公众号知识写入请使用 Vercel/Docker 后端。",
                }
            )
            return
        self._unavailable()

    def do_POST(self):
        self._unavailable()

    def do_PUT(self):
        self._unavailable()

    def _unavailable(self):
        self._json(
            {
                "detail": (
                    "EdgeOne 当前部署为轻后端：支持前端、健康检查、配置和只读学习摘要。"
                    "用户设置、公众号写入、盘后扫描、实时行情和财务采集请使用 Vercel/Docker 后端或后续独立 worker。"
                )
            },
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )

    def _json(self, payload: object, *, status: int = HTTPStatus.OK, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def api_path(raw_path: str) -> str:
    path = urlparse(raw_path).path
    if path.startswith("/api"):
        path = path[4:]
    return path or "/"


def public_config() -> dict[str, object]:
    database_url = os.getenv("STOCK_LAB_DATABASE_URL")
    return {
        "project_root": "/edgeone/cloud-functions",
        "data_dir": str(DATA_DIR),
        "database_url": mask_database_url(database_url) if database_url else str(DATA_DIR / "stock_lab.sqlite3"),
        "feishu_app_id": os.getenv("STOCK_LAB_FEISHU_APP_ID", "cli_a6f82b2e17f6100c"),
        "feishu_app_secret": "***" if os.getenv("STOCK_LAB_FEISHU_APP_SECRET") else None,
        "client_auth_secret": "***",
        "screen": asdict(SCREEN),
        "strategy": asdict(STRATEGY),
    }


def mask_database_url(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    return f"{scheme}://***@{rest.split('@', 1)[1]}"


def empty_learning_summary() -> dict[str, object]:
    return {
        "total_cases": 0,
        "buy_cases": 0,
        "winning_buys": 0,
        "losing_buys": 0,
        "missed_cases": 0,
        "buy_win_rate": 0.0,
        "avg_buy_return": 0.0,
        "avg_max_drawdown": 0.0,
        "user_feedback_count": 0,
        "top_failure_reasons": [],
        "top_success_reasons": [],
        "strategy_insights": {
            "status": "collecting",
            "message": "EdgeOne 轻后端只提供只读占位摘要；真实学习库请使用 Vercel/Docker 后端或后续 worker。",
            "recommendations": [],
        },
        "recent_records": [],
        "updated_at": None,
    }


def strategy_optimization() -> dict[str, object]:
    return {
        "target_win_rate": 80.0,
        "current_metrics": {
            "total_cases": 0,
            "buy_cases": 0,
            "buy_win_rate": 0.0,
            "avg_buy_return": 0.0,
            "avg_max_drawdown": 0.0,
            "top_failure_reasons": [],
        },
        "current_strategy": asdict(STRATEGY),
        "proposed_strategy": asdict(STRATEGY),
        "parameter_changes": [],
        "experiment_plan": [],
        "disclaimer": "EdgeOne 轻后端只提供只读占位建议；策略进化以数据库和真实回测样本为准。",
        "experiment": {},
        "experiment_history": [],
    }
