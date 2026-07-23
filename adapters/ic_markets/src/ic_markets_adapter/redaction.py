from __future__ import annotations

import json
import re
from typing import Any

SENSITIVE_KEYS = re.compile(
    r"(authorization|cookie|token|access.?token|refresh.?token|password|passwd|secret|mfa|"
    r"otp|account|login|session.?id|balance|profile)",
    re.IGNORECASE,
)
BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")
QUERY_TOKEN = re.compile(r"(?i)([?&](?:token|access_token|auth|session)=)[^&\s]+")
JSON_SENSITIVE_FIELD = re.compile(
    r"""(?ix)
    ("(?:authorization|cookie|token|access_?token|refresh_?token|password|passwd|
    secret|mfa|otp|account|login|session_?id|balance|profile)"\s*:\s*)
    ("(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?|true|false|null)
    """
)


def redact(value: Any) -> tuple[Any, list[str]]:
    redactions: list[str] = []

    def visit(item: Any, path: str) -> Any:
        if isinstance(item, dict):
            result: dict[str, Any] = {}
            for key, child in item.items():
                child_path = f"{path}.{key}"
                if SENSITIVE_KEYS.search(str(key)):
                    result[str(key)] = "[REDACTED]"
                    redactions.append(child_path)
                else:
                    result[str(key)] = visit(child, child_path)
            return result
        if isinstance(item, list):
            return [visit(child, f"{path}[{index}]") for index, child in enumerate(item)]
        if isinstance(item, str):
            stripped = item.strip()
            if stripped.startswith(("{", "[")):
                try:
                    parsed = json.loads(item)
                except (json.JSONDecodeError, ValueError):
                    parsed = None
                if isinstance(parsed, dict | list):
                    sanitized = visit(parsed, path)
                    return json.dumps(sanitized, sort_keys=True, separators=(",", ":"))
            redacted = BEARER.sub("Bearer [REDACTED]", item)
            redacted = QUERY_TOKEN.sub(r"\1[REDACTED]", redacted)
            redacted = JSON_SENSITIVE_FIELD.sub(r'\1"[REDACTED]"', redacted)
            if redacted != item:
                redactions.append(path)
            return redacted
        return item

    return visit(value, "$"), sorted(set(redactions))
