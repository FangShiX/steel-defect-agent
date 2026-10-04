"""Shared redaction helpers for diagnostic and durable Agent traces."""

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_SECRET_KEY_RE = re.compile(r"(?i)(password|token|authorization|api[_-]?key|secret)")
_PRIVATE_KEY_RE = re.compile(r"(?i)^(content|query|prompt|text|body|reply|file_content)$")
_KEY_VALUE_RE = re.compile(
    r"(?i)(password|token|authorization|api[_-]?key|secret)\s*[:=]\s*([^\s,;]+)"
)
_URL_RE = re.compile(r"https?://[^\s\]}>,;]+")


def redact_text(value: Any) -> str:
    """Redact secrets and object URLs from text before it reaches a log."""
    text = str(value)
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", text)
    text = _KEY_VALUE_RE.sub(r"\1=[redacted]", text)
    return _URL_RE.sub("[resource-url-redacted]", text)


def redact_value(value: Any, key: str = "") -> Any:
    """Recursively redact private fields while retaining trace structure."""
    normalized_key = key.lower()
    if _SECRET_KEY_RE.search(normalized_key):
        return "[redacted]"
    if _PRIVATE_KEY_RE.match(normalized_key):
        return "[private-content-redacted]"
    if isinstance(value, dict):
        return {item_key: redact_value(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item, key) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return json.dumps(redact_value(parsed), ensure_ascii=False)
        parsed_url = urlparse(value)
        if parsed_url.scheme in {"http", "https"}:
            return f"[signed-resource:{Path(parsed_url.path).name or 'object'}]"
        if normalized_key in {"path", "image_path", "file_path", "image", "url"}:
            return f"[private-path:{Path(value).name}]"
        return redact_text(value)
    return value
