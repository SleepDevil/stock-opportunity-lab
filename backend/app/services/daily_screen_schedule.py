from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from app.config import AppConfig
from app.services.daily_screen_card import build_daily_screen_card
from app.services.data_provider import AkShareProvider, MarketDataProvider
from app.services.learning_store import list_watchlist_commentary_subscriptions
from app.services.market_factor_snapshot import (
    SnapshotMarketDataProvider,
    load_or_fetch_market_factor_snapshot,
)
from app.services.notification_settings import load_notification_settings
from app.services.notifications import send_feishu_card
from app.services.screen_generation import generate_screen_response
from app.services.screen_report_store import (
    claim_screen_delivery,
    finish_screen_delivery,
    load_screen_report_snapshot_record,
)
from app.services.stock_quotes import load_market_index


LOGGER = logging.getLogger("stock_lab.daily_screen_schedule")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
CLOSE_SLOT_LABEL = "15:00"
MARKET_FRESHNESS_LIMIT = timedelta(minutes=20)
SCHEDULED_GENERATION_SOURCE = "scheduled_close"


class CloseSlot(Protocol):
    trade_date: str
    label: str


class ScreenDeliveryTarget(Protocol):
    user_email: str | None
    chat_id: str
    platform_url: str


class CloseSnapshotNotCurrentError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConfiguredScreenDeliveryTarget:
    user_email: str | None
    chat_id: str
    platform_url: str


@dataclass(frozen=True)
class ManualCloseSlot:
    trade_date: str
    label: str = CLOSE_SLOT_LABEL


def run_daily_close_screen(
    config: AppConfig,
    slot: CloseSlot,
    now: datetime,
    *,
    targets: list[ScreenDeliveryTarget] | None = None,
    market_provider: MarketDataProvider | None = None,
    allow_completed_close_snapshot: bool = False,
) -> dict[str, Any] | None:
    if slot.label != CLOSE_SLOT_LABEL:
        return None

    delivery_targets = targets if targets is not None else configured_screen_delivery_targets(config)
    existing = load_screen_report_snapshot_record(config, slot.trade_date)
    market_snapshot: dict[str, Any] | None = None
    if existing and existing.get("generation_source") == SCHEDULED_GENERATION_SOURCE:
        report = existing["payload"]
        generated_at = str(existing.get("generated_at") or now.isoformat(timespec="seconds"))
        generation_status = "reused"
    else:
        market = load_market_index(refresh=True)
        validate_close_market_snapshot(
            market,
            slot.trade_date,
            now,
            allow_completed_close_snapshot=allow_completed_close_snapshot,
        )
        source_provider = market_provider or AkShareProvider(config)
        snapshot = load_or_fetch_market_factor_snapshot(config, slot.trade_date, source_provider)
        snapshot_provider = SnapshotMarketDataProvider(
            trade_date=slot.trade_date,
            frame=snapshot.frame,
            delegate=source_provider,
        )
        market_snapshot = {
            "status": snapshot.acquisition,
            "source": snapshot.source,
            "captured_at": snapshot.captured_at,
            "row_count": snapshot.row_count,
        }
        report = generate_screen_response(
            provider=snapshot_provider,
            config=config,
            trade_date=slot.trade_date,
            refresh=False,
            limit=config.screen.max_candidates,
            enrich=False,
            exclude_boards=scheduled_excluded_boards(config, delivery_targets),
            generation_source=SCHEDULED_GENERATION_SOURCE,
            generated_at=now.isoformat(timespec="seconds"),
            include_trends=False,
            require_complete_factors=True,
        ).model_dump(mode="json")
        generated_at = now.isoformat(timespec="seconds")
        generation_status = "generated"

    deliveries = deliver_screen_report(config, report, delivery_targets, generated_at=generated_at)
    failed = any(result.get("status") == "failed" for result in deliveries)
    return {
        "status": "completed_with_delivery_errors" if failed else "completed",
        "trade_date": slot.trade_date,
        "generation": generation_status,
        "candidate_count": len(report.get("candidates") or []),
        "filtered_count": int(report.get("filtered_count") or 0),
        "market_snapshot": market_snapshot,
        "deliveries": deliveries,
    }


def run_manual_daily_close_screen(
    config: AppConfig,
    *,
    now: datetime | None = None,
    targets: list[ScreenDeliveryTarget] | None = None,
    market_provider: MarketDataProvider | None = None,
) -> dict[str, Any] | None:
    current = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    if current.weekday() >= 5:
        raise CloseSnapshotNotCurrentError("非工作日不生成收盘量化选股")
    if (current.hour, current.minute) < (15, 0):
        raise CloseSnapshotNotCurrentError("尚未收盘，不能手动生成收盘量化选股")
    slot = ManualCloseSlot(trade_date=current.strftime("%Y%m%d"))
    return run_daily_close_screen(
        config,
        slot,
        current,
        targets=targets,
        market_provider=market_provider,
        allow_completed_close_snapshot=True,
    )


def deliver_screen_report(
    config: AppConfig,
    report: dict[str, Any],
    targets: list[ScreenDeliveryTarget],
    *,
    generated_at: str,
) -> list[dict[str, Any]]:
    trade_date = str(report.get("trade_date") or "")
    destinations: dict[str, ScreenDeliveryTarget] = {}
    for target in targets:
        if target.chat_id and target.platform_url:
            destinations.setdefault(target.chat_id, target)

    results: list[dict[str, Any]] = []
    for chat_id, target in destinations.items():
        idempotency_key = claim_screen_delivery(config, trade_date, chat_id)
        if not idempotency_key:
            results.append({"chat_id": chat_id, "status": "deduplicated"})
            continue
        try:
            card = build_daily_screen_card(report, target.platform_url, generated_at=generated_at)
            sent = send_feishu_card(card, chat_id, config=config)
        except Exception as exc:
            LOGGER.exception("Daily screen card delivery failed for %s", chat_id)
            finish_screen_delivery(config, idempotency_key, "failed", str(exc))
            results.append({"chat_id": chat_id, "status": "failed", "message": str(exc)})
            continue
        if not sent:
            message = "飞书量化选股卡片发送失败"
            finish_screen_delivery(config, idempotency_key, "failed", message)
            results.append({"chat_id": chat_id, "status": "failed", "message": message})
            continue
        finish_screen_delivery(config, idempotency_key, "sent", "飞书量化选股卡片已发送")
        results.append({"chat_id": chat_id, "status": "sent"})
    return results


def scheduled_excluded_boards(config: AppConfig, targets: list[ScreenDeliveryTarget]) -> list[str]:
    for target in targets:
        if not target.user_email:
            continue
        settings = load_notification_settings(config, target.user_email)
        if settings.board_exclusion_enabled:
            return list(settings.excluded_boards)
        return []
    return []


def configured_screen_delivery_targets(config: AppConfig) -> list[ConfiguredScreenDeliveryTarget]:
    subscriptions = list_watchlist_commentary_subscriptions(config)
    if subscriptions:
        return [
            ConfiguredScreenDeliveryTarget(
                user_email=str(subscription.get("user_email") or "") or None,
                chat_id=str(subscription.get("feishu_chat_id") or ""),
                platform_url=str(subscription.get("platform_url") or ""),
            )
            for subscription in subscriptions
            if subscription.get("enabled")
            and subscription.get("feishu_chat_id")
            and subscription.get("platform_url")
        ]

    defaults = load_notification_settings(config, None)
    if not defaults.watchlist_commentary_feishu_enabled:
        return []
    if not defaults.watchlist_commentary_feishu_chat_id or not defaults.watchlist_commentary_platform_url:
        return []
    return [
        ConfiguredScreenDeliveryTarget(
            user_email=None,
            chat_id=defaults.watchlist_commentary_feishu_chat_id,
            platform_url=defaults.watchlist_commentary_platform_url,
        )
    ]


def validate_close_market_snapshot(
    market: dict[str, Any],
    trade_date: str,
    now: datetime,
    *,
    allow_completed_close_snapshot: bool = False,
) -> None:
    snapshot_date = str(market.get("trade_date") or "").replace("-", "")
    updated_at = parse_datetime(market.get("updated_at"))
    if snapshot_date != trade_date or not updated_at or updated_at.strftime("%Y%m%d") != trade_date:
        raise CloseSnapshotNotCurrentError("指数行情不是当前交易日，跳过收盘量化选股")
    age = now.astimezone(SHANGHAI_TZ) - updated_at.astimezone(SHANGHAI_TZ)
    if age < timedelta(minutes=-2) or age > MARKET_FRESHNESS_LIMIT:
        if allow_completed_close_snapshot and has_completed_close_point(market, trade_date):
            return
        raise CloseSnapshotNotCurrentError("指数行情更新时间超出可接受范围，跳过收盘量化选股")


def has_completed_close_point(market: dict[str, Any], trade_date: str) -> bool:
    for point in reversed(market.get("points") or []):
        if not isinstance(point, dict):
            continue
        point_time = parse_datetime(point.get("time"))
        if not point_time or point_time.astimezone(SHANGHAI_TZ).strftime("%Y%m%d") != trade_date:
            continue
        return (point_time.hour, point_time.minute) >= (15, 0)
    return False


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip().replace(" ", "T")
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed
