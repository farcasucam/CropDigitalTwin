"""Structured logging setup for all process entry points."""

from __future__ import annotations

import logging


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s correlation_id=%(correlation_id)s %(message)s",
    )


class CorrelationLoggerAdapter(logging.LoggerAdapter):
    def process(self, message: str, kwargs: object) -> tuple[str, object]:
        extra = getattr(kwargs, "get", lambda _: {})("extra", {}) or {}
        extra.setdefault("correlation_id", self.extra.get("correlation_id", "-"))
        kwargs["extra"] = extra
        return message, kwargs