"""Logging setup with secret redaction (tokens never reach the logs)."""

from __future__ import annotations

import logging
import re

_TOKEN_PATTERN = re.compile(r"xox[bap]-[A-Za-z0-9-]+")


class _SecretRedactor(logging.Filter):
    def __init__(self, secrets: list[str]) -> None:
        self._secrets = [s for s in secrets if s and len(s) >= 8]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _TOKEN_PATTERN.sub("***", message)
        for secret in self._secrets:
            if secret in redacted:
                redacted = redacted.replace(secret, "***")
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(level: str, *, secrets: list[str]) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(_SecretRedactor(secrets))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
