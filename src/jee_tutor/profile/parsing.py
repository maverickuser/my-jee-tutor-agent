from __future__ import annotations

from urllib.parse import unquote, urlparse

from jee_tutor.profile.models import ParsedStudentS3Context


def parse_student_context_from_s3_path(value: str) -> ParsedStudentS3Context | None:
    text = value.strip()
    if not text:
        return None

    bucket: str | None = None
    if text.startswith("s3://"):
        parsed = urlparse(text)
        if parsed.scheme != "s3" or not parsed.netloc:
            return None
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
    else:
        key = text.lstrip("/")

    parts = [unquote(part) for part in key.split("/") if part]
    context = _parse_parts(parts)
    if context is None:
        return None
    return ParsedStudentS3Context(bucket=bucket, prefix=key.rstrip("/"), **context)


def _parse_parts(parts: list[str]) -> dict[str, str] | None:
    try:
        users_index = parts.index("users")
        tests_index = parts.index("tests", users_index + 3)
        subjects_index = parts.index("subjects", tests_index + 2)
        questions_index = parts.index("questions", subjects_index + 2)
    except ValueError:
        return None

    if (
        tests_index != users_index + 3
        or subjects_index != tests_index + 2
        or questions_index != subjects_index + 2
    ):
        return None

    student_id = parts[users_index + 1]
    student_name = parts[users_index + 2]
    test_name = parts[tests_index + 1]
    subject = parts[subjects_index + 1]
    if not all([student_id, student_name, test_name, subject]):
        return None

    questions_prefix = "/".join(parts[: questions_index + 1])
    return {
        "student_id": student_id,
        "student_name": student_name,
        "test_name": test_name,
        "subject": subject,
        "questions_prefix": questions_prefix,
    }
