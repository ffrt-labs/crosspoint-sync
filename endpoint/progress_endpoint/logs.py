"""One JSON object per log line. Only named fields are written, so nothing leaks by accident."""

import json
import logging
import sys
from datetime import UTC, datetime

EXTRA_FIELDS = ("reason", "id", "document")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for name in EXTRA_FIELDS:
            if hasattr(record, name):
                line[name] = getattr(record, name)
        if record.exc_info:
            line["error"] = self.formatException(record.exc_info)
        return json.dumps(line)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("progress_endpoint")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
