from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any, Callable, Literal

from app.models import TaskAcceptedResponse, TaskStatusResponse


TaskStatus = Literal["queued", "running", "completed", "failed"]


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
            created_at=self.created_at,
            updated_at=self.updated_at,
            result=self.result,
            error=self.error,
        )

    def to_accepted_response(self) -> TaskAcceptedResponse:
        return TaskAcceptedResponse(
            task_id=self.task_id,
            kind=self.kind,
            trade_date=self.trade_date,
            status=self.status,
            message=self.message,
            notification_email=self.notification_email,
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
            )
            self._records[task_id] = record

        self._executor.submit(self._run, task_id, work, notify)
        return record.to_accepted_response()

    def _run(
        self,
        task_id: str,
        work: Callable[[], dict[str, Any]],
        notify: Callable[[TaskRecord], None] | None,
    ) -> None:
        self._update(task_id, status="running", message="后台任务运行中，完成后会通知。")
        try:
            result = work()
            record = self._update(task_id, status="completed", message="后台任务已完成。", result=result, error=None)
        except Exception as exc:
            record = self._update(task_id, status="failed", message="后台任务失败。", error=str(exc))

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
            record.updated_at = utc_now()
            return TaskRecord(**record.__dict__)


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
