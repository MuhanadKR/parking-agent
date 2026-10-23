"""Request-local logging context, also copied into synchronous worker threads."""

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field


request_id: ContextVar[str] = ContextVar("request_id", default="-")


@dataclass
class RunMetrics:
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tools: list[str] = field(default_factory=list)
    stop_reason: str = "not_run"


# A new mutable object per request lets worker-thread updates reach middleware.
run_metrics: ContextVar[RunMetrics | None] = ContextVar("run_metrics", default=None)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True
