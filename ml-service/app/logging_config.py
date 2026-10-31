"""
Logging setup.

Policy (enforced by convention in every module, and by the filter below as a safety net):
  * Never log report text, de-identified text, prompts, or model output. Log lengths, counts,
    IDs (pipeline_run_id, RxCUI, set_id), status codes and durations instead.
  * Credentials are scrubbed from every log line by `SecretRedactingFilter`.
"""

from __future__ import annotations

import logging
import re

_SECRET_PATTERNS = [
    (re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?bearer\s+)[^\s'\",]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "[REDACTED_KEY]"),
    (re.compile(r"(?i)(api[_-]?key['\"]?\s*[:=]\s*['\"]?)[^\s&'\",]+"), r"\1[REDACTED]"),
]


def redact_secrets(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class SecretRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed format args: keep the record, drop args
            message = str(record.msg)
        record.msg = redact_secrets(message)
        record.args = None
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_pharmaguard_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    handler.addFilter(SecretRedactingFilter())
    root.addHandler(handler)
    root.setLevel(level)
    # Third-party HTTP clients log full URLs (which can carry api_key query params) at INFO/DEBUG.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._pharmaguard_configured = True  # type: ignore[attr-defined]

