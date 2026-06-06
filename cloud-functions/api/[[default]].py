from __future__ import annotations

import os
from pathlib import Path
import sys

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response


FUNCTION_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = FUNCTION_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("STOCK_LAB_DATA_DIR", "/tmp/stock-opportunity-lab")

from app.config import CONFIG  # noqa: E402
from app.models import (  # noqa: E402
    ApiMessage,
    LearningFeedbackRequest,
    LearningFeedbackResponse,
    LearningSummary,
    NotificationSettings,
    NotificationSettingsUpdate,
    StrategyOptimizationResponse,
    WechatArticleIngestRequest,
    WechatArticleResponse,
    WechatKnowledgeResponse,
    WechatSubscriptionRequest,
    WechatSubscriptionResponse,
)
from app.services.client_auth import (  # noqa: E402
    CSRF_COOKIE_NAME,
    ClientAuthError,
    issue_csrf_token,
    is_https_request,
    reject_untrusted_origin_if_present,
    require_client_auth,
)
from app.services.learning import append_user_feedback, load_learning_summary  # noqa: E402
from app.services.notification_settings import load_notification_settings, save_notification_settings  # noqa: E402
from app.services.notifications import send_feishu_tip  # noqa: E402
from app.services.strategy_optimizer import build_strategy_optimization  # noqa: E402
from app.services.wechat_knowledge import (  # noqa: E402
    create_wechat_subscription as save_wechat_subscription,
    ingest_wechat_article,
    list_wechat_articles,
    list_wechat_subscriptions,
)


app = FastAPI(title="Stock Opportunity Lab EdgeOne API", version="0.1.0")


def require_frontend_client(request: Request) -> None:
    try:
        require_client_auth(request, CONFIG)
    except ClientAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/", response_model=ApiMessage)
@app.get("/api", response_model=ApiMessage)
@app.get("/health", response_model=ApiMessage)
@app.get("/api/health", response_model=ApiMessage)
def health() -> ApiMessage:
    return ApiMessage(ok=True, message="ready")


@app.get("/config")
@app.get("/api/config")
def get_config():
    return CONFIG.public_dict()


@app.get("/client-auth")
@app.get("/api/client-auth")
def get_client_auth(request: Request, response: Response) -> dict[str, str]:
    try:
        reject_untrusted_origin_if_present(request)
    except ClientAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    token = issue_csrf_token(CONFIG)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        httponly=True,
        secure=is_https_request(request),
        samesite="lax",
        max_age=12 * 60 * 60,
        path="/",
    )
    return {"csrf_token": token}


@app.get(
    "/notification-settings",
    response_model=NotificationSettings,
    dependencies=[Depends(require_frontend_client)],
)
@app.get(
    "/api/notification-settings",
    response_model=NotificationSettings,
    dependencies=[Depends(require_frontend_client)],
)
def get_notification_settings(user_email: str | None = None) -> NotificationSettings:
    try:
        return load_notification_settings(CONFIG, user_email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put(
    "/notification-settings",
    response_model=NotificationSettings,
    dependencies=[Depends(require_frontend_client)],
)
@app.put(
    "/api/notification-settings",
    response_model=NotificationSettings,
    dependencies=[Depends(require_frontend_client)],
)
def put_notification_settings(request: NotificationSettingsUpdate) -> NotificationSettings:
    try:
        return save_notification_settings(
            CONFIG,
            request.user_email,
            board_exclusion_enabled=request.board_exclusion_enabled,
            excluded_boards=request.excluded_boards,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/notification-settings/test",
    response_model=ApiMessage,
    dependencies=[Depends(require_frontend_client)],
)
@app.post(
    "/api/notification-settings/test",
    response_model=ApiMessage,
    dependencies=[Depends(require_frontend_client)],
)
def test_notification(request: NotificationSettingsUpdate | None = Body(default=None)) -> ApiMessage:
    settings = load_notification_settings(CONFIG, request.user_email if request else None)
    if not settings.user_email:
        raise HTTPException(status_code=400, detail="请先在策略设置里保存飞书账号邮箱")
    ok = send_feishu_tip("Stock Opportunity Lab 测试通知：飞书机器人已经打通。", settings.user_email)
    return ApiMessage(ok=ok, message="测试通知已发送" if ok else "通知发送失败，请检查飞书机器人配置和账号邮箱")


@app.get("/wechat-knowledge", response_model=WechatKnowledgeResponse)
@app.get("/api/wechat-knowledge", response_model=WechatKnowledgeResponse)
def wechat_knowledge() -> WechatKnowledgeResponse:
    return WechatKnowledgeResponse(
        subscriptions=list_wechat_subscriptions(CONFIG),
        articles=list_wechat_articles(CONFIG),
        capability_note="微信没有稳定公开接口可订阅任意公众号全部历史消息；当前支持手动导入文章 URL，或为合规 RSS/feed 预留 feed_url。",
    )


@app.post("/wechat-subscriptions", response_model=WechatSubscriptionResponse)
@app.post("/api/wechat-subscriptions", response_model=WechatSubscriptionResponse)
def create_wechat_subscription(request: WechatSubscriptionRequest) -> WechatSubscriptionResponse:
    try:
        result = save_wechat_subscription(
            CONFIG,
            source_name=request.source_name,
            sample_url=request.sample_url,
            feed_url=request.feed_url,
        )
        return WechatSubscriptionResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/wechat-articles", response_model=WechatArticleResponse)
@app.post("/api/wechat-articles", response_model=WechatArticleResponse)
def ingest_wechat_article_api(request: WechatArticleIngestRequest) -> WechatArticleResponse:
    try:
        result = ingest_wechat_article(
            CONFIG,
            source_name=request.source_name,
            article_url=request.article_url,
            html=request.html,
        )
        return WechatArticleResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/learning-summary", response_model=LearningSummary)
@app.get("/api/learning-summary", response_model=LearningSummary)
def learning_summary() -> LearningSummary:
    return LearningSummary(**load_learning_summary(CONFIG))


@app.post("/learning-feedback", response_model=LearningFeedbackResponse)
@app.post("/api/learning-feedback", response_model=LearningFeedbackResponse)
def learning_feedback(request: LearningFeedbackRequest) -> LearningFeedbackResponse:
    try:
        result = append_user_feedback(
            CONFIG,
            screen_date=request.screen_date,
            actual_date=request.actual_date,
            code=request.code,
            note=request.note,
            author=request.author,
        )
        return LearningFeedbackResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/strategy-optimization", response_model=StrategyOptimizationResponse)
@app.get("/api/strategy-optimization", response_model=StrategyOptimizationResponse)
def strategy_optimization() -> StrategyOptimizationResponse:
    return StrategyOptimizationResponse(**build_strategy_optimization(CONFIG))


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def unavailable(full_path: str):
    raise HTTPException(
        status_code=503,
        detail=(
            "EdgeOne 当前部署为轻后端：支持配置、用户设置、学习库和公众号知识。"
            "盘后扫描、实时行情和财务采集请使用 Vercel/Docker 后端或后续独立采集 worker。"
        ),
    )
