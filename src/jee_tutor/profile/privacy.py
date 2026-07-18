from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def redact_email(value: str | None) -> str | None:
    if value is None:
        return None
    email = normalize_email(value)
    if "@" not in email:
        return "[redacted-email]"
    local_part, domain = email.split("@", 1)
    visible = local_part[:1] if local_part else ""
    return f"{visible}***@{domain}"


def redact_student_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    sensitive_keys = {
        "recipient_email",
        "email",
        "student_id",
        "student_name",
        "test_name",
    }
    for key, value in payload.items():
        key_text = str(key)
        normalized_key = key_text.casefold()
        if normalized_key in {"recipient_email", "email"}:
            redacted[key_text] = redact_email(str(value)) if value is not None else None
            continue
        if normalized_key in sensitive_keys:
            redacted[key_text] = "[redacted]"
            continue
        if normalized_key == "image_s3_prefix" and value is not None:
            redacted[key_text] = redact_student_s3_path(str(value))
            continue
        redacted[key_text] = value
    return redacted


def redact_student_s3_path(value: str) -> str:
    parts = value.split("/")
    try:
        users_index = parts.index("users")
        tests_index = parts.index("tests", users_index + 3)
        subjects_index = parts.index("subjects", tests_index + 2)
    except ValueError:
        return value
    redacted = list(parts)
    redacted[users_index + 1] = "[student-id]"
    redacted[users_index + 2] = "[student-name]"
    redacted[tests_index + 1] = "[test-name]"
    if subjects_index + 1 < len(redacted):
        redacted[subjects_index + 1] = "[subject]"
    return "/".join(redacted)
