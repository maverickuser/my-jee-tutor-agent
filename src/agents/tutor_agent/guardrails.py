import base64
import binascii
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import boto3

from agents.tutor_agent.config_loader import LLMConfig


GuardrailSource = Literal["INPUT", "OUTPUT"]


@dataclass(frozen=True)
class GuardrailSettings:
    enabled: bool
    identifier: str | None = None
    version: str = "DRAFT"
    region_name: str | None = None
    output_scope: str = "INTERVENTIONS"
    fail_closed: bool = True
    include_image: bool = True


@dataclass(frozen=True)
class GuardrailCheck:
    allowed: bool
    message: str | None = None
    action_reason: str | None = None
    detected_pii: list[str] | None = None
    response: dict[str, Any] | None = None


class RuntimeGuardrail:
    def __init__(
        self,
        settings: GuardrailSettings | None = None,
        environ: Mapping[str, str] | None = None,
        config: LLMConfig | None = None,
        client: Any | None = None,
    ):
        self.environ = environ if environ is not None else os.environ
        self.config = config or LLMConfig.load(self.environ.get("LLM_CONFIG_FILE"))
        self.settings = settings or self._resolve_settings()
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled and self.settings.identifier)

    def check_input(
        self,
        *,
        question_context: str | None,
        image_data_uri: str | None = None,
    ) -> GuardrailCheck:
        content = self._build_input_content(question_context, image_data_uri)
        return self._apply("INPUT", content)

    def check_output(self, analysis: str) -> GuardrailCheck:
        return self._apply("OUTPUT", self._text_content(analysis))

    def _apply(self, source: GuardrailSource, content: list[dict[str, Any]]) -> GuardrailCheck:
        if not self.enabled or not content:
            return GuardrailCheck(allowed=True)

        try:
            response = self.client.apply_guardrail(
                guardrailIdentifier=self.settings.identifier,
                guardrailVersion=self.settings.version,
                source=source,
                content=content,
                outputScope=self.settings.output_scope,
            )
        except Exception as exc:
            if self.settings.fail_closed:
                return GuardrailCheck(
                    allowed=False,
                    message="Runtime guardrail check failed.",
                    action_reason=str(exc),
                )
            return GuardrailCheck(allowed=True, action_reason=str(exc))

        if response.get("action") != "GUARDRAIL_INTERVENED":
            return GuardrailCheck(allowed=True, response=response)

        detected_pii = self._detected_sensitive_information(response)
        return GuardrailCheck(
            allowed=False,
            message=self._blocked_message(response, detected_pii),
            action_reason=self._action_reason(response, detected_pii),
            detected_pii=detected_pii,
            response=response,
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.settings.region_name,
            )
        return self._client

    def _resolve_settings(self) -> GuardrailSettings:
        return GuardrailSettings(
            enabled=self._bool_setting("BEDROCK_GUARDRAIL_ENABLED", "enabled", False),
            identifier=self._setting("BEDROCK_GUARDRAIL_ID", "identifier"),
            version=self._setting("BEDROCK_GUARDRAIL_VERSION", "version", "DRAFT") or "DRAFT",
            region_name=self._setting("BEDROCK_GUARDRAIL_REGION", "region")
            or self.environ.get("AWS_REGION")
            or self.environ.get("AWS_DEFAULT_REGION"),
            output_scope=self._setting(
                "BEDROCK_GUARDRAIL_OUTPUT_SCOPE",
                "output_scope",
                "INTERVENTIONS",
            )
            or "INTERVENTIONS",
            fail_closed=self._bool_setting("BEDROCK_GUARDRAIL_FAIL_CLOSED", "fail_closed", True),
            include_image=self._bool_setting("BEDROCK_GUARDRAIL_INCLUDE_IMAGE", "include_image", True),
        )

    def _setting(
        self,
        env_key: str,
        config_key: str,
        default: str | None = None,
    ) -> str | None:
        return self.environ.get(env_key) or self.config.get("guardrails", config_key, default)

    def _bool_setting(self, env_key: str, config_key: str, default: bool) -> bool:
        value = self.environ.get(env_key)
        if value is None:
            value = self.config.get("guardrails", config_key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _build_input_content(
        self,
        question_context: str | None,
        image_data_uri: str | None,
    ) -> list[dict[str, Any]]:
        content = self._text_content(question_context)
        if self.settings.include_image and image_data_uri:
            image_content = self._image_content(image_data_uri)
            if image_content:
                content.append(image_content)
        return content

    @staticmethod
    def _text_content(text: str | None) -> list[dict[str, Any]]:
        if not text or not text.strip():
            return []
        return [{"text": {"text": text.strip()}}]

    @staticmethod
    def _image_content(image_data_uri: str) -> dict[str, Any] | None:
        metadata, separator, encoded = image_data_uri.partition(",")
        if not separator or ";base64" not in metadata:
            return None

        image_format = metadata.removeprefix("data:image/").split(";")[0].lower()
        if image_format == "jpg":
            image_format = "jpeg"
        if image_format not in {"jpeg", "png"}:
            return None

        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return None

        return {"image": {"format": image_format, "source": {"bytes": image_bytes}}}

    @staticmethod
    def _first_output_text(response: dict[str, Any]) -> str | None:
        for output in response.get("outputs", []):
            text = output.get("text")
            if text:
                return text
        return None

    @classmethod
    def _blocked_message(cls, response: dict[str, Any], detected_pii: list[str]) -> str | None:
        return cls._first_output_text(response) or (
            "Request blocked because it contains sensitive personal information."
            if detected_pii
            else None
        )

    @staticmethod
    def _action_reason(response: dict[str, Any], detected_pii: list[str]) -> str | None:
        action_reason = response.get("actionReason")
        if action_reason:
            return action_reason
        if detected_pii:
            return "Sensitive information detected: " + ", ".join(detected_pii)
        return None

    @classmethod
    def _detected_sensitive_information(cls, response: dict[str, Any]) -> list[str]:
        detected: set[str] = set()
        for assessment in response.get("assessments", []):
            policy = assessment.get("sensitiveInformationPolicy", {})
            cls._add_detected_policy_items(detected, policy.get("piiEntities", []), "type")
            cls._add_detected_policy_items(detected, policy.get("regexes", []), "name")
        return sorted(detected)

    @staticmethod
    def _add_detected_policy_items(
        detected: set[str],
        items: list[dict[str, Any]],
        label_key: str,
    ) -> None:
        for item in items:
            if item.get("action") in {None, "NONE"}:
                continue
            label = item.get(label_key)
            if label:
                detected.add(str(label))
