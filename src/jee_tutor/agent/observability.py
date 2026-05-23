from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
import logging
import os
from typing import Any, Iterator

from jee_tutor.agent.config_loader import LLMConfig


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


class LangfuseObservability:
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.load()

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

    @property
    def flush_after_invocation(self) -> bool:
        return bool(self.config.get("langfuse", "flush_after_invocation", False))

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

        langfuse = get_client()
        attributes = {
            "trace_name": self.trace_name,
            "user_id": user_id,
            "session_id": session_id,
            "tags": tags,
            "metadata": metadata,
        }
        attributes = {key: value for key, value in attributes.items() if value is not None}
        attribute_context = (
            propagate_attributes(**attributes) if propagate_attributes else nullcontext()
        )

        with attribute_context:
            with langfuse.start_as_current_observation(
                as_type="span",
                name=self.trace_name,
                input=input_payload,
            ) as span:
                yield span

    @contextmanager
    def generation_span(
        self,
        *,
        model: str,
        input_payload: dict[str, Any],
        prompt: Any = None,
    ) -> Iterator[Any]:
        if not self.enabled:
            yield None
            return

        langfuse = get_client()
        with langfuse.start_as_current_observation(
            as_type="generation",
            name=self.generation_name,
            model=model,
            input=input_payload,
            prompt=prompt,
        ) as generation:
            yield generation

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

        langfuse = get_client()
        for score in scores:
            kwargs = {
                "name": score.name,
                "value": score.value,
                "comment": score.comment,
            }
            if score.data_type:
                kwargs["data_type"] = score.data_type
            langfuse.score_current_trace(
                **{key: value for key, value in kwargs.items() if value is not None}
            )

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
        langfuse.flush()

    def flush(self) -> None:
        if self.enabled and self.flush_after_invocation:
            get_client().flush()
