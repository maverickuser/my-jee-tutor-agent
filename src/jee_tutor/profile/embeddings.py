from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import os
from typing import Any, Protocol

import boto3
from litellm import embedding
from pydantic import BaseModel, ConfigDict, Field, field_validator

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.profile.evidence import ProfileEvidenceItem

DEFAULT_PROFILE_EMBEDDING_MODEL = "bedrock/amazon.titan-embed-text-v2:0"
DEFAULT_EMBEDDING_INPUT_VERSION = "v1"
DEFAULT_PROFILE_EMBEDDING_DIMENSIONS = 256

EmbeddingFunction = Callable[..., Mapping[str, Any]]


class EvidenceEmbeddingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnosis_json_s3_uri: str = Field(min_length=1)
    embedding_key: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    embedding_input_version: str = Field(min_length=1)
    embedding_text_hash: str = Field(min_length=1)
    embedding: list[float] = Field(min_length=1)
    created_at: str = Field(min_length=1)

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: list[float]) -> list[float]:
        if not all(isinstance(component, int | float) for component in value):
            raise ValueError("Embedding components must be numeric.")
        return [float(component) for component in value]


class EvidenceEmbeddingStore(Protocol):
    def get_embedding(
        self,
        *,
        diagnosis_json_s3_uri: str,
        embedding_key: str,
    ) -> EvidenceEmbeddingRecord | None: ...

    def put_embedding(self, record: EvidenceEmbeddingRecord) -> None: ...


class EvidenceEmbeddingClient(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class ProfileEmbeddingSettings:
    model: str
    dimensions: int | None = None
    api_key: str | None = None
    api_base: str | None = None

    def to_litellm_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.model}
        if self.dimensions is not None:
            kwargs["dimensions"] = self.dimensions
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        return kwargs


class ProfileEmbeddingConfig:
    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        config: Any | None = None,
    ):
        self.environ = environ or os.environ
        self.config = config or LLMConfig.load()

    def resolve(self) -> ProfileEmbeddingSettings:
        model = (
            self.environ.get("PROFILE_EMBEDDING_MODEL")
            or _config_get(self.config, "profile_embedding", "model", DEFAULT_PROFILE_EMBEDDING_MODEL)
        )
        dimensions = _config_get(
            self.config,
            "profile_embedding",
            "dimensions",
            DEFAULT_PROFILE_EMBEDDING_DIMENSIONS,
        )
        if self.environ.get("PROFILE_EMBEDDING_DIMENSIONS"):
            dimensions = int(self.environ["PROFILE_EMBEDDING_DIMENSIONS"])
        api_base = (
            self.environ.get("LITELLM_BASE_URL")
            or _config_get(self.config, "litellm", "api_base")
        )
        return ProfileEmbeddingSettings(
            model=model,
            dimensions=int(dimensions) if dimensions else None,
            api_key=_api_key_for_model(model, self.environ),
            api_base=api_base,
        )


class LiteLLMEvidenceEmbeddingClient:
    def __init__(
        self,
        *,
        config: ProfileEmbeddingConfig | None = None,
        embedding_fn: EmbeddingFunction | None = None,
    ):
        self.config = config or ProfileEmbeddingConfig()
        self.embedding_fn = embedding_fn or embedding
        self._settings: ProfileEmbeddingSettings | None = None

    @property
    def model(self) -> str:
        return self._resolved_settings().model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        settings = self._resolved_settings()
        response = self.embedding_fn(
            **settings.to_litellm_kwargs(),
            input=texts,
        )
        return [
            [float(component) for component in item["embedding"]]
            for item in response["data"]
        ]

    def _resolved_settings(self) -> ProfileEmbeddingSettings:
        if self._settings is None:
            self._settings = self.config.resolve()
        return self._settings


class InMemoryEvidenceEmbeddingStore:
    def __init__(self):
        self.records: dict[tuple[str, str], EvidenceEmbeddingRecord] = {}

    def get_embedding(
        self,
        *,
        diagnosis_json_s3_uri: str,
        embedding_key: str,
    ) -> EvidenceEmbeddingRecord | None:
        return self.records.get((diagnosis_json_s3_uri, embedding_key))

    def put_embedding(self, record: EvidenceEmbeddingRecord) -> None:
        self.records[(record.diagnosis_json_s3_uri, record.embedding_key)] = record


@dataclass(frozen=True)
class EvidenceEmbeddingStoreConfig:
    table_name: str = ""
    region: str = "ap-south-1"
    enabled: bool = False

    @classmethod
    def from_environment(cls) -> "EvidenceEmbeddingStoreConfig":
        table_name = os.getenv("EVIDENCE_EMBEDDING_TABLE_NAME", "").strip()
        enabled_value = os.getenv("EVIDENCE_EMBEDDING_ENABLED", "true").strip().lower()
        enabled = enabled_value in {"1", "true", "yes", "on"} and bool(table_name)
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-south-1"
        return cls(table_name=table_name, region=region, enabled=enabled)


class DynamoDbEvidenceEmbeddingStore:
    def __init__(self, *, table_name: str, region: str):
        self.table_name = table_name
        self.region = region
        self._table = None

    @classmethod
    def from_environment(cls) -> EvidenceEmbeddingStore:
        config = EvidenceEmbeddingStoreConfig.from_environment()
        if not config.enabled:
            return InMemoryEvidenceEmbeddingStore()
        return cls(table_name=config.table_name, region=config.region)

    def get_embedding(
        self,
        *,
        diagnosis_json_s3_uri: str,
        embedding_key: str,
    ) -> EvidenceEmbeddingRecord | None:
        response = self._table_client().get_item(
            Key={
                "diagnosis_json_s3_uri": diagnosis_json_s3_uri,
                "embedding_key": embedding_key,
            }
        )
        item = response.get("Item")
        if not item:
            return None
        return EvidenceEmbeddingRecord.model_validate(item)

    def put_embedding(self, record: EvidenceEmbeddingRecord) -> None:
        self._table_client().put_item(Item=record.model_dump(mode="json"))

    def _table_client(self):
        if self._table is None:
            self._table = boto3.resource("dynamodb", region_name=self.region).Table(
                self.table_name
            )
        return self._table


class EvidenceEmbeddingService:
    def __init__(
        self,
        *,
        store: EvidenceEmbeddingStore | None = None,
        client: EvidenceEmbeddingClient | None = None,
        input_version: str = DEFAULT_EMBEDDING_INPUT_VERSION,
    ):
        self.store = store or build_evidence_embedding_store()
        self.client = client or LiteLLMEvidenceEmbeddingClient()
        self.input_version = input_version

    def ensure_embeddings(
        self,
        *,
        subject: str,
        evidence_items: list[ProfileEvidenceItem],
    ) -> dict[str, EvidenceEmbeddingRecord]:
        records: dict[str, EvidenceEmbeddingRecord] = {}
        missing: list[tuple[ProfileEvidenceItem, str, str]] = []
        for item in evidence_items:
            embedding_text = build_embedding_input_text(subject=subject, evidence=item)
            text_hash = embedding_text_hash(embedding_text)
            embedding_key = build_embedding_key(
                evidence_id=item.evidence_id,
                embedding_model=self.client.model,
                embedding_input_version=self.input_version,
            )
            existing = self.store.get_embedding(
                diagnosis_json_s3_uri=item.diagnosis_json_s3_uri,
                embedding_key=embedding_key,
            )
            if existing is not None and existing.embedding_text_hash == text_hash:
                records[item.evidence_id] = existing
                continue
            missing.append((item, embedding_text, text_hash))

        if missing:
            embeddings = self.client.embed([entry[1] for entry in missing])
            if len(embeddings) != len(missing):
                raise ValueError("Embedding client returned an unexpected number of embeddings.")
            for (item, _embedding_text, text_hash), vector in zip(missing, embeddings, strict=True):
                record = EvidenceEmbeddingRecord(
                    diagnosis_json_s3_uri=item.diagnosis_json_s3_uri,
                    embedding_key=build_embedding_key(
                        evidence_id=item.evidence_id,
                        embedding_model=self.client.model,
                        embedding_input_version=self.input_version,
                    ),
                    evidence_id=item.evidence_id,
                    embedding_model=self.client.model,
                    embedding_input_version=self.input_version,
                    embedding_text_hash=text_hash,
                    embedding=vector,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                self.store.put_embedding(record)
                records[item.evidence_id] = record
        return records


def build_evidence_embedding_store() -> EvidenceEmbeddingStore:
    return DynamoDbEvidenceEmbeddingStore.from_environment()


def build_embedding_input_text(*, subject: str, evidence: ProfileEvidenceItem) -> str:
    return "\n".join(
        [
            f"Subject: {subject}",
            f"Chapter: {evidence.chapter}",
            f"Topic: {evidence.topic}",
            f"Exact concept gap: {evidence.exact_concept_gap}",
            f"Likely student thought: {evidence.likely_thought}",
            f"Why wrong: {evidence.why_wrong}",
            f"Deep-dive recommendation: {evidence.deep_dive_recommendation}",
        ]
    )


def embedding_text_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def build_embedding_key(
    *,
    evidence_id: str,
    embedding_model: str,
    embedding_input_version: str,
) -> str:
    return f"{evidence_id}#{embedding_model}#{embedding_input_version}"


def _api_key_for_model(model: str, environ: Mapping[str, str]) -> str | None:
    normalized = model.casefold()
    if normalized.startswith("openai/"):
        return environ.get("OPENAI_API_KEY") or environ.get("LITELLM_API_KEY")
    if normalized.startswith("gemini/"):
        return environ.get("GOOGLE_API_KEY") or environ.get("LITELLM_API_KEY")
    return environ.get("LITELLM_API_KEY") or None


def _config_get(
    config: Any,
    section: str,
    key: str,
    default: Any = None,
) -> Any:
    if hasattr(config, "section"):
        return config.get(section, key, default)
    value = config.get(section, {})
    if not isinstance(value, Mapping):
        return default
    return value.get(key, default)
