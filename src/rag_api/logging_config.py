"""Structured JSON logging with OTEL trace/span ID injection.

Every log record emitted while an OTEL span is active will include trace_id
and span_id fields. In CloudWatch Logs Insights, filter by trace_id to pull
all log lines for a specific X-Ray trace — bridging traces and logs.
"""
import json
import logging
import time
from typing import override

from opentelemetry import trace


class _OTELJsonFormatter(logging.Formatter):
    @override
    def format(self, record: logging.LogRecord) -> str:
        span = trace.get_current_span()
        ctx = span.get_span_context()
        entry: dict[str, object] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if ctx.is_valid:
            entry["trace_id"] = format(ctx.trace_id, "032x")
            entry["span_id"] = format(ctx.span_id, "016x")
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_OTELJsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
