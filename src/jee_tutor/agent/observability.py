from collections.abc import Mapping
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass
import logging
import os
import time
from typing import Any, Iterator

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.model_routing import active_model_bundle


try:
    from langfuse import get_client, propagate_attributes
except ImportError:  # pragma: no cover - keeps local imports resilient before install
    get_client = None
    propagate_attributes = None


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvaluationScore:
    name: str
    value: float | int | str
    data_type: str | None = None
    comment: str | None = None


def safe_provider_response_metadata(response: Any) -> dict[str, Any]:
    """Extract non-content provider identifiers when the response exposes them."""

    values = (
        response
        if isinstance(response, Mapping)
        else getattr(response, "__dict__", {})
    )
    metadata: dict[str, Any] = {}
    request_id = values.get("id") or values.get("request_id")
    if isinstance(request_id, str) and request_id:
        metadata["provider_request_id"] = request_id

    choices = values.get("choices")
    first_choice = choices[0] if isinstance(choices, list) and choices else None
    choice_values = (
        first_choice
        if isinstance(first_choice, Mapping)
        else getattr(first_choice, "__dict__", {})
        if first_choice is not None
        else {}
    )
    finish_reason = choice_values.get("finish_reason")
    if isinstance(finish_reason, str) and finish_reason:
        metadata["finish_reason"] = finish_reason

    hidden = values.get("_hidden_params")
    if isinstance(hidden, Mapping):
        hidden_request_id = hidden.get("request_id")
        if not metadata.get("provider_request_id") and isinstance(hidden_request_id, str):
            metadata["provider_request_id"] = hidden_request_id
    return metadata


class LangfuseObservability:
    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        default_metadata: dict[str, Any] | None = None,
    ):
        self.config = config or LLMConfig.load()
        model_bundle = active_model_bundle()
        self.default_metadata = {
            **(model_bundle.trace_metadata if model_bundle is not None else {}),
            **(default_metadata or {}),
        }

    @property
    def enabled(self) -> bool:
        if get_client is None:
            return False
        configured = bool(self.config.get("langfuse", "enabled", True))
        has_credentials = bool(
            os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
        )
        return configured and has_credentials

    @property
    def trace_name(self) -> str:
        return self.config.get("langfuse", "trace_name", "jee-tutor-agentcore-invocation")

    @property
    def generation_name(self) -> str:
        return self.config.get("langfuse", "generation_name", "vision-question-analysis")

    @contextmanager
    def invocation_span(
        self,
        *,
        input_payload: dict[str, Any],
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[Any]:
        if not self.enabled:
            yield None
            return

        try:
            langfuse = get_client()
        except Exception as exc:
            self._log_observability_failure("invocation_start", exc, metadata)
            yield None
            return
        attributes = {
            "trace_name": self.trace_name,
            "user_id": user_id,
            "session_id": session_id,
            "tags": tags,
            "metadata": self._metadata(metadata),
        }
        attributes = {key: value for key, value in attributes.items() if value is not None}
        attribute_context = (
            propagate_attributes(**attributes) if propagate_attributes else nullcontext()
        )

        stack = ExitStack()
        try:
            stack.enter_context(attribute_context)
            span = stack.enter_context(
                langfuse.start_as_current_observation(
                    as_type="span",
                    name=self.trace_name,
                    input=input_payload,
                    metadata=self._metadata(metadata),
                )
            )
        except Exception as exc:
            self._log_observability_failure("invocation_start", exc, metadata)
            try:
                stack.close()
            except Exception as close_exc:
                self._log_observability_failure("invocation_close", close_exc, metadata)
            yield None
            return

        body_error: BaseException | None = None
        try:
            yield _SafeObservation(
                span,
                on_error=lambda exc: self._log_observability_failure(
                    "invocation_update", exc, metadata
                ),
            )
        except BaseException as exc:
            body_error = exc
            raise
        finally:
            try:
                stack.__exit__(
                    type(body_error) if body_error is not None else None,
                    body_error,
                    body_error.__traceback__ if body_error is not None else None,
                )
            except Exception as exc:
                self._log_observability_failure("invocation_close", exc, metadata)
            self._flush_client(langfuse)

    @contextmanager
    def generation_span(
        self,
        *,
        model: str,
        input_payload: dict[str, Any],
        prompt: Any = None,
        metadata: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> Iterator[Any]:
        with self._provider_span(
            as_type="generation",
            name=name or self.generation_name,
            model=model,
            input_payload=input_payload,
            prompt=prompt,
            metadata=metadata,
        ) as generation:
            yield generation

    @contextmanager
    def embedding_span(
        self,
        *,
        model: str,
        input_payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        name: str = "profile-evidence-embedding",
    ) -> Iterator[Any]:
        with self._provider_span(
            as_type="embedding",
            name=name,
            model=model,
            input_payload=input_payload,
            metadata=metadata,
        ) as embedding:
            yield embedding

    @contextmanager
    def _provider_span(
        self,
        *,
        as_type: str,
        name: str,
        model: str,
        input_payload: dict[str, Any],
        prompt: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[Any]:
        failure_metadata = {
            "model": model,
            "provider": model.split("/", 1)[0] if "/" in model else None,
            "operation": name,
            **(metadata or {}),
        }
        span_metadata = self._metadata(failure_metadata)
        if not self.enabled:
            yield _LocalProviderObservation(
                operation=name,
                metadata={**self.default_metadata, **failure_metadata},
            )
            return
        try:
            langfuse = get_client()
            manager = langfuse.start_as_current_observation(
                as_type=as_type,
                name=name,
                model=model,
                input=input_payload,
                prompt=prompt,
                metadata=span_metadata,
            )
            observation = manager.__enter__()
        except Exception as exc:
            self._log_observability_failure(
                f"{as_type}_start", exc, failure_metadata
            )
            yield _LocalProviderObservation(
                operation=name,
                metadata={**self.default_metadata, **failure_metadata},
            )
            return

        body_error: BaseException | None = None
        try:
            yield _SafeObservation(
                observation,
                on_error=lambda exc: self._log_observability_failure(
                    f"{as_type}_update", exc, failure_metadata
                ),
            )
        except BaseException as exc:
            body_error = exc
            raise
        finally:
            try:
                manager.__exit__(
                    type(body_error) if body_error is not None else None,
                    body_error,
                    body_error.__traceback__ if body_error is not None else None,
                )
            except Exception as exc:
                self._log_observability_failure(
                    f"{as_type}_close", exc, failure_metadata
                )

    def get_text_prompt(self, name: str | None, fallback: str) -> tuple[str, Any | None]:
        if not self.enabled or not name:
            return fallback, None

        try:
            prompt = get_client().get_prompt(name, type="text", fallback=fallback)
            return prompt.compile(), prompt
        except Exception as exc:
            logger.warning(
                "langfuse_prompt_fetch_failed prompt_name=%s error_type=%s error=%s",
                name,
                exc.__class__.__name__,
                exc or "[no message]",
                exc_info=True,
            )
            return fallback, None

    def score_current_trace(self, scores: list[EvaluationScore]) -> None:
        if not self.enabled or not scores:
            return

        try:
            langfuse = get_client()
        except Exception as exc:
            self._log_observability_failure("score_start", exc, None)
            return
        for score in scores:
            kwargs = {
                "name": score.name,
                "value": score.value,
                "comment": score.comment,
            }
            if score.data_type:
                kwargs["data_type"] = score.data_type
            try:
                langfuse.score_current_trace(
                    **{key: value for key, value in kwargs.items() if value is not None}
                )
            except Exception as exc:
                self._log_observability_failure("score_update", exc, None)

    def publish_deploy_summary(
        self,
        *,
        name: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        scores: list[EvaluationScore],
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        if not self.enabled:
            return

        try:
            langfuse = get_client()
            with langfuse.start_as_current_observation(
                as_type="span",
                name=name,
                input=input_payload,
                output=output_payload,
                metadata=metadata,
            ):
                langfuse.update_current_trace(name=name, metadata=metadata, tags=tags)
                self.score_current_trace(scores)
            self._flush_client(langfuse)
        except Exception as exc:
            self._log_observability_failure("deploy_summary", exc, metadata)

    def flush(self) -> None:
        if self.enabled:
            try:
                self._flush_client(get_client())
            except Exception as exc:
                self._log_observability_failure("flush_start", exc, None)

    @staticmethod
    def _flush_client(langfuse: Any) -> None:
        try:
            langfuse.flush()
        except Exception as exc:
            logger.warning(
                "langfuse_flush_failed error_type=%s error=%s",
                type(exc).__name__,
                exc or "[no message]",
            )

    def _metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any] | None:
        combined = {**self.default_metadata, **(metadata or {})}
        return combined or None

    @staticmethod
    def _log_observability_failure(
        operation: str,
        exc: Exception,
        metadata: dict[str, Any] | None,
    ) -> None:
        safe_metadata = {
            key: value
            for key, value in (metadata or {}).items()
            if key
            in {
                "attempt",
                "execution_profile",
                "max_attempts",
                "model",
                "operation",
                "provider",
                "status",
            }
        }
        logger.warning(
            "langfuse_operation_failed operation=%s error_type=%s metadata=%s",
            operation,
            type(exc).__name__,
            safe_metadata,
        )


class _SafeObservation:
    def __init__(self, observation: Any, *, on_error) -> None:
        self._observation = observation
        self._on_error = on_error

    def update(self, **kwargs: Any) -> None:
        try:
            self._observation.update(**kwargs)
        except Exception as exc:
            self._on_error(exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._observation, name)


class _LocalProviderObservation:
    """Redacted fallback event used when Langfuse cannot accept an observation."""

    def __init__(self, *, operation: str, metadata: dict[str, Any]) -> None:
        self.operation = operation
        self.metadata = metadata
        self.started_at = time.monotonic()
        logger.info(
            "llm_provider_attempt_local operation=%s model=%s provider=%s "
            "execution_profile=%s attempt=%s",
            operation,
            metadata.get("model"),
            metadata.get("provider"),
            metadata.get("execution_profile"),
            metadata.get("attempt"),
        )

    def update(self, **kwargs: Any) -> None:
        output = kwargs.get("output")
        output_values = output if isinstance(output, dict) else {}
        status = output_values.get("status")
        if status is None:
            status = "failed" if output_values.get("error_type") else "succeeded"
        usage = kwargs.get("usage_details")
        cost = kwargs.get("cost_details")
        logger.info(
            "llm_provider_result_local operation=%s model=%s attempt=%s status=%s "
            "duration_ms=%s usage=%s cost=%s error_type=%s",
            self.operation,
            self.metadata.get("model"),
            self.metadata.get("attempt"),
            status,
            round((time.monotonic() - self.started_at) * 1000, 3),
            usage if isinstance(usage, dict) else {},
            cost if isinstance(cost, dict) else {},
            output_values.get("error_type"),
        )
