"""Protocol interfaces for external runtime effects."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from jee_tutor.api.invocation import AgentInvocationRecord
from jee_tutor.curriculum.taxonomy import CurriculumTaxonomy
from jee_tutor.email.models import EmailDeliveryOutcome
from jee_tutor.invocation.image_inputs import ResolvedImage


class ImageResolverPort(Protocol):
    def resolve_images(
        self,
        *,
        image_data_uri: str | None,
        image_s3_prefix: str | None,
    ) -> list[ResolvedImage]: ...


class GuardrailPort(Protocol):
    def check_input(
        self,
        *,
        question_context: str | None,
        image_data_uris: list[str],
    ) -> Any: ...

    def check_output(self, text: str) -> Any: ...


class ObservabilityPort(Protocol):
    def invocation_span(
        self,
        *,
        input_payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Any: ...


class TutorWorkflowPort(Protocol):
    def __call__(
        self,
        *,
        image_data_uris: list[str],
        question_context: str | None = None,
        expected_question_numbers: list[str | None] | None = None,
        invocation_id: str | None = None,
        status_store: Any = None,
    ) -> str: ...


class LLMVisionCompletionPort(Protocol):
    transport_attempt_count: int

    def analyze_vision(
        self,
        image_data_uris: list[str],
        *,
        expected_question_numbers: list[str | None] | None = None,
    ) -> str: ...


class StatusStorePort(Protocol):
    def upsert_invocation(self, record: AgentInvocationRecord) -> None: ...

    def update_invocation(self, invocation_id: str, **updates: Any) -> None: ...

    def append_llm_call(self, invocation_id: str, call: Any) -> None: ...


class ArtifactWriterPort(Protocol):
    def write_for_invocation(self, *, analysis_markdown: str, invocation: Any) -> Any: ...


class EmailDeliveryPort(Protocol):
    def request_delivery(
        self,
        *,
        recipient_email: str,
        pdf_uri: str,
        invocation_id: str | None,
        idempotency_key: str | None,
    ) -> EmailDeliveryOutcome: ...


class IdempotencyStorePort(Protocol):
    def claim(self, key: str, payload: dict[str, Any]) -> Any: ...

    def complete(self, key: str, response: dict[str, Any]) -> None: ...

    def abandon(self, key: str) -> None: ...


class TaxonomyLoaderPort(Protocol):
    def load(self) -> CurriculumTaxonomy | None: ...


Factory = Callable[[], Any]
