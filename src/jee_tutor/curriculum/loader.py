from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse

import boto3

from jee_tutor.curriculum.taxonomy import CurriculumTaxonomy
from jee_tutor.curriculum.validator import CurriculumValidator


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CurriculumTaxonomyConfig:
    s3_uri: str = ""
    local_path: str = ""
    cache_ttl_seconds: float = 3600.0
    required: bool = False
    region_name: str | None = None

    @classmethod
    def from_environment(cls, environ: dict[str, str] | None = None) -> "CurriculumTaxonomyConfig":
        env = environ if environ is not None else os.environ
        return cls(
            s3_uri=env.get("CURRICULUM_TAXONOMY_S3_URI", "").strip(),
            local_path=env.get("CURRICULUM_TAXONOMY_LOCAL_PATH", "").strip(),
            cache_ttl_seconds=float(env.get("CURRICULUM_TAXONOMY_CACHE_TTL_SECONDS", "3600")),
            required=_bool(env.get("CURRICULUM_TAXONOMY_REQUIRED", "false")),
            region_name=env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION"),
        )


@dataclass
class _CachedTaxonomy:
    taxonomy: CurriculumTaxonomy
    source: str
    fingerprint: str
    expires_at: float


class CurriculumTaxonomyLoader:
    def __init__(
        self,
        *,
        config: CurriculumTaxonomyConfig | None = None,
        s3_client: Any | None = None,
        monotonic: Any = time.monotonic,
    ):
        self.config = config or CurriculumTaxonomyConfig.from_environment()
        self.s3_client = s3_client
        self.monotonic = monotonic
        self._cache: _CachedTaxonomy | None = None

    def load(self) -> CurriculumTaxonomy | None:
        source = self._source()
        if source is None:
            if self.config.required:
                raise RuntimeError("taxonomy_unavailable: curriculum taxonomy source is required.")
            logger.info("curriculum_taxonomy_disabled reason=no_source")
            return None

        cached = self._cache
        if cached is not None and cached.source == source and cached.expires_at > self.monotonic():
            return cached.taxonomy

        try:
            if self.config.s3_uri:
                taxonomy, fingerprint = self._load_s3(self.config.s3_uri, cached)
            else:
                taxonomy, fingerprint = self._load_local(self.config.local_path, cached)
        except Exception:
            logger.exception("curriculum_taxonomy_load_failed source=%s", source)
            if cached is not None and cached.source == source:
                return cached.taxonomy
            if self.config.required:
                raise
            return None

        self._cache = _CachedTaxonomy(
            taxonomy=taxonomy,
            source=source,
            fingerprint=fingerprint,
            expires_at=self.monotonic() + self.config.cache_ttl_seconds,
        )
        logger.info(
            "curriculum_taxonomy_loaded version=%s source=%s",
            taxonomy.version,
            source,
        )
        return taxonomy

    def _source(self) -> str | None:
        if self.config.s3_uri:
            return self.config.s3_uri
        if self.config.local_path:
            return self.config.local_path
        return None

    def _load_s3(
        self,
        s3_uri: str,
        cached: _CachedTaxonomy | None,
    ) -> tuple[CurriculumTaxonomy, str]:
        bucket, key = _parse_s3_uri(s3_uri)
        head = self._s3().head_object(Bucket=bucket, Key=key)
        etag = str(head.get("ETag", "")).strip('"')
        if cached is not None and cached.fingerprint == etag:
            return cached.taxonomy, cached.fingerprint
        response = self._s3().get_object(Bucket=bucket, Key=key)
        body = response["Body"].read()
        return CurriculumTaxonomy.model_validate_json(body), etag or _sha256(body)

    def _load_local(
        self,
        local_path: str,
        cached: _CachedTaxonomy | None,
    ) -> tuple[CurriculumTaxonomy, str]:
        path = Path(local_path)
        body = path.read_bytes()
        stat = path.stat()
        fingerprint = f"{stat.st_mtime_ns}:{_sha256(body)}"
        if cached is not None and cached.fingerprint == fingerprint:
            return cached.taxonomy, cached.fingerprint
        return CurriculumTaxonomy.model_validate_json(body), fingerprint

    def _s3(self):
        if self.s3_client is None:
            self.s3_client = boto3.client("s3", region_name=self.config.region_name)
        return self.s3_client


def build_curriculum_validator_from_environment(
    environ: dict[str, str] | None = None,
) -> CurriculumValidator | None:
    config = CurriculumTaxonomyConfig.from_environment(environ)
    if not config.s3_uri and not config.local_path and not config.required:
        return None
    return CurriculumValidator(loader=CurriculumTaxonomyLoader(config=config))


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
