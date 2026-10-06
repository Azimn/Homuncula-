from __future__ import annotations

import hmac
import os
import re
import secrets
from pathlib import Path
from typing import Any

TOKEN_FILENAME = "owner.token"
REDACTED = "<redacted>"
SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
    }
)

def load_or_create_owner_token(home: Path) -> str:
    supplied = os.environ.get("HOMUNCULA_OWNER_TOKEN", "").strip()
    if supplied:
        return supplied

    path = home / TOKEN_FILENAME
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token

    token = secrets.token_urlsafe(48)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token

def token_matches(expected: str, supplied: str | None) -> bool:
    if not supplied:
        return False
    return hmac.compare_digest(expected, supplied)

def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            lowered = key.lower()
            if any(sensitive in lowered for sensitive in SENSITIVE_KEYS):
                result[key] = REDACTED
            else:
                result[key] = redact_payload(child)
        return result
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_payload(item) for item in value)
    return value


_TEXT_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|token)"
        r"(\s*[=:]\s*)([^\s,;]+)"
    ),
)


def redact_text(text: str) -> str:
    value = str(text)
    value = _TEXT_SECRET_PATTERNS[0].sub(r"\1" + REDACTED, value)
    value = _TEXT_SECRET_PATTERNS[1].sub(
        lambda match: match.group(1) + match.group(2) + REDACTED,
        value,
    )
    return value
