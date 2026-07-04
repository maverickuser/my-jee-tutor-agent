from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class EmailConfig:
    from_address: str
    subject_template: str
    body_template: str
    region: str | None = None
    delivery_provider: str = "lambda"
    delivery_function_arn: str | None = None

    @classmethod
    def from_env(cls) -> "EmailConfig":
        return cls(
            from_address=os.getenv("EMAIL_FROM_ADDRESS", "").strip(),
            subject_template=os.getenv("EMAIL_SUBJECT_TEMPLATE", "").strip(),
            body_template=os.getenv("EMAIL_BODY_TEMPLATE", "").strip(),
            region=os.getenv("EMAIL_REGION", "").strip() or None,
            delivery_provider=os.getenv("EMAIL_DELIVERY_PROVIDER", "lambda").strip() or "lambda",
            delivery_function_arn=os.getenv("EMAIL_DELIVERY_FUNCTION_ARN", "").strip() or None,
        )

    def validate(self, *, require_delivery_function: bool = False) -> list[str]:
        errors: list[str] = []
        if not self.from_address:
            errors.append("EMAIL_FROM_ADDRESS is required.")
        if not self.subject_template:
            errors.append("EMAIL_SUBJECT_TEMPLATE is required.")
        if not self.body_template:
            errors.append("EMAIL_BODY_TEMPLATE is required.")
        if require_delivery_function and self.delivery_provider == "lambda" and not self.delivery_function_arn:
            errors.append("EMAIL_DELIVERY_FUNCTION_ARN is required when using lambda delivery.")
        return errors
