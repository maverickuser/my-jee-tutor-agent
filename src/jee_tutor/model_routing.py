"""Request-scoped model selection for CD and live runtime invocations."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
import os


CD_GENERATION_MODEL = "gemini/gemini-2.5-flash-lite"
CD_EMBEDDING_MODEL = "gemini/gemini-embedding-001"
LIVE_GENERATION_MODEL = "gemini/gemini-3.6-flash"
LIVE_EMBEDDING_MODEL = "gemini/gemini-embedding-2"


class ExecutionProfile(StrEnum):
    CD = "cd"
    LIVE = "live"


@dataclass(frozen=True)
class ModelBundle:
    execution_profile: ExecutionProfile
    generation_model: str
    embedding_model: str

    @property
    def trace_metadata(self) -> dict[str, str]:
        return {
            "execution_profile": self.execution_profile.value,
            "generation_model": self.generation_model,
            "embedding_model": self.embedding_model,
        }


_ACTIVE_MODEL_BUNDLE: ContextVar[ModelBundle | None] = ContextVar(
    "jee_tutor_active_model_bundle",
    default=None,
)


def resolve_model_bundle(
    execution_profile: ExecutionProfile,
    environ: Mapping[str, str] | None = None,
) -> ModelBundle:
    values = environ if environ is not None else os.environ
    if execution_profile is ExecutionProfile.CD:
        return ModelBundle(
            execution_profile=execution_profile,
            generation_model=values.get("CD_GENERATION_MODEL", CD_GENERATION_MODEL),
            embedding_model=values.get("CD_EMBEDDING_MODEL", CD_EMBEDDING_MODEL),
        )
    return ModelBundle(
        execution_profile=execution_profile,
        generation_model=values.get("LIVE_GENERATION_MODEL", LIVE_GENERATION_MODEL),
        embedding_model=values.get("LIVE_EMBEDDING_MODEL", LIVE_EMBEDDING_MODEL),
    )


def active_model_bundle() -> ModelBundle | None:
    return _ACTIVE_MODEL_BUNDLE.get()


@contextmanager
def use_model_bundle(model_bundle: ModelBundle) -> Iterator[ModelBundle]:
    token = _ACTIVE_MODEL_BUNDLE.set(model_bundle)
    try:
        yield model_bundle
    finally:
        _ACTIVE_MODEL_BUNDLE.reset(token)


def is_gemini_36_model(model: str) -> bool:
    normalized = model.removeprefix("gemini/").removeprefix("google/")
    return normalized == "gemini-3.6-flash"


__all__ = [
    "CD_EMBEDDING_MODEL",
    "CD_GENERATION_MODEL",
    "LIVE_EMBEDDING_MODEL",
    "LIVE_GENERATION_MODEL",
    "ExecutionProfile",
    "ModelBundle",
    "active_model_bundle",
    "is_gemini_36_model",
    "resolve_model_bundle",
    "use_model_bundle",
]
