import logging
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(r"password|token|secret|authorization|cookie|api[_-]?key", re.I)


def _redact(value: Any) -> Any:
    if isinstance(value, MutableMapping):
        return {
            key: REDACTED if _SENSITIVE_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(_redact(item) for item in value)
    return value


def redact_sensitive_fields(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: mask values whose key looks sensitive, at any nesting depth."""
    redacted: MutableMapping[str, Any] = _redact(event_dict)
    return redacted


def configure_logging(level: str = "INFO", *, json_logs: bool = True) -> None:
    renderer: structlog.typing.Processor
    if json_logs:
        renderer = structlog.processors.JSONRenderer()
        exception_processors: list[structlog.typing.Processor] = [
            structlog.processors.dict_tracebacks
        ]
    else:
        renderer = structlog.dev.ConsoleRenderer()
        exception_processors = []

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_sensitive_fields,
            *exception_processors,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
