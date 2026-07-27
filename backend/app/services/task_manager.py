from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from threading import Lock
from typing import Any, Callable, Literal

from app.models import TaskAcceptedResponse, TaskStatusResponse


TaskStatus = Literal["queued", "running", "completed", "failed"]
logger = logging.getLogger(__name__)


@dataclass
class TaskRecord:
    task_id: str
    kind: str
    trade_date: str
    status: TaskStatus
    message: str
    created_at: str
    updated_at: str
    notification_email: str | None = None
    progress: int = 0
    progress_label: str | None = None
    logs: list[dict[str, Any]] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_status_response(self) -> TaskStatusResponse:
        return TaskStatusResponse(
            task_id=self.task_id,
            kind=self.kind,
            trade_date=self.trade_date,
            status=self.status,
            message=self.message,
            notification_email=self.notification_email,
            progress=self.progress,
            progress_label=self.progress_label,
            created_at=self.created_at,
            updated_at=self.updated_at,
            result=self.result,
            error=self.error,
            logs=self.logs or [],
        )

    def to_accepted_response(self) -> TaskAcceptedResponse:
        return TaskAcceptedResponse(
            task_id=self.task_id,
            kind=self.kind,
            trade_date=self.trade_date,
            status=self.status,
            message=self.message,
            notification_email=self.notification_email,
            progress=self.progress,
            progress_label=self.progress_label,
        )


class TaskManager:
    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="stock-lab-task")
        self._records: dict[str, TaskRecord] = {}
        self._lock = Lock()

    def get(self, task_id: str) -> TaskStatusResponse | None:
        with self._lock:
            record = self._records.get(task_id)
            return record.to_status_response() if record else None

    def enqueue(
        self,
        *,
        task_id: str,
        kind: str,
        trade_date: str,
        message: str,
        notification_email: str | None,
        work: Callable[[], dict[str, Any]],
        notify: Callable[[TaskRecord], None] | None = None,
    ) -> TaskAcceptedResponse:
        with self._lock:
            existing = self._records.get(task_id)
            if existing and existing.status in {"queued", "running"}:
                return existing.to_accepted_response()

            now = utc_now()
            record = TaskRecord(
                task_id=task_id,
                kind=kind,
                trade_date=trade_date,
                status="queued",
                message=message,
                created_at=now,
                updated_at=now,
                notification_email=notification_email,
                progress=0,
                progress_label="等待后台执行",
                logs=[
                    {
                        "timestamp": now,
                        "progress": 0,
                        "message": "任务已提交，等待后台线程执行。",
                        "elapsed_seconds": None,
                    }
                ],
            )
            self._records[task_id] = record
            accepted = record.to_accepted_response()

        self._executor.submit(self._run, task_id, work, notify)
        return accepted

    def report_progress(
        self,
        task_id: str,
        progress: int,
        message: str,
        *,
        elapsed_seconds: float | None = None,
    ) -> TaskStatusResponse | None:
        normalized_progress = max(0, min(100, int(progress)))
        with self._lock:
            record = self._records.get(task_id)
            if not record:
                return None
            now = utc_now()
            record.progress = normalized_progress
            record.progress_label = message
            record.updated_at = now
            record.logs = list(record.logs or [])
            record.logs.append(
                {
                    "timestamp": now,
                    "progress": normalized_progress,
                    "message": message,
                    "elapsed_seconds": elapsed_seconds,
                }
            )
            if len(record.logs) > 80:
                record.logs = record.logs[-80:]
            snapshot = record.to_status_response()
        elapsed_text = f" elapsed={elapsed_seconds:.1f}s" if elapsed_seconds is not None else ""
        logger.info("task=%s progress=%s%% %s%s", task_id, normalized_progress, message, elapsed_text)
        return snapshot

    def _run(
        self,
        task_id: str,
        work: Callable[[], dict[str, Any]],
        notify: Callable[[TaskRecord], None] | None,
    ) -> None:
        self._update(task_id, status="running", message="后台任务运行中，完成后会通知。")
        self.report_progress(task_id, 5, "后台任务已启动。")
        try:
            result = work()
            record = self._update(
                task_id,
                status="completed",
                message="后台任务已完成。",
                progress=100,
                progress_label="扫描完成。",
                result=result,
                error=None,
                add_log=True,
            )
        except Exception as exc:
            record = self._update(
                task_id,
                status="failed",
                message="后台任务失败。",
                progress_label="扫描失败。",
                error=str(exc),
                add_log=True,
            )

        if notify:
            try:
                notify(record)
            except Exception as exc:
                self._update(task_id, error=f"{record.error or ''}\n通知发送失败: {exc}".strip())

    def _update(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        message: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        progress: int | None = None,
        progress_label: str | None = None,
        add_log: bool = False,
    ) -> TaskRecord:
        with self._lock:
            record = self._records[task_id]
            if status:
                record.status = status
            if message:
                record.message = message
            if result is not None:
                record.result = result
            if error is not None:
                record.error = error
            if progress is not None:
                record.progress = max(0, min(100, int(progress)))
            if progress_label is not None:
                record.progress_label = progress_label
            record.updated_at = utc_now()
            if add_log:
                record.logs = list(record.logs or [])
                record.logs.append(
                    {
                        "timestamp": record.updated_at,
                        "progress": record.progress,
                        "message": record.progress_label or message or record.message,
                        "elapsed_seconds": None,
                    }
                )
            return TaskRecord(**record.__dict__)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
