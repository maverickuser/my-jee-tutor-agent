from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import tomllib
from typing import Any, Protocol

from litellm import completion
from pydantic import BaseModel, ConfigDict, Field, field_validator

from jee_tutor.profile.semantic import LongitudinalEvidencePack


logger = logging.getLogger(__name__)
PROFILE_REPORT_SCHEMA_NAME = "student_longitudinal_profile_report"
PROFILE_REPORT_SCHEMA_VERSION = "1.0"
PROFILE_REPORT_MODEL = "gemini/gemini-2.5-pro"
DEFAULT_LLM_TIMEOUT_SECONDS = 180
DEFAULT_CONFIG_PATHS = (
    Path("config/llm.toml"),
    Path("src/config/llm.toml"),
)
CompletionFunction = Callable[..., dict]


@dataclass(frozen=True)
class ProfileReportModelSettings:
    model: str
    api_key: str | None = None
    api_base: str | None = None
    aws_region_name: str | None = None
    completion_options: dict[str, Any] | None = None

    def to_litellm_kwargs(self) -> dict[str, Any]:
        kwargs = deepcopy(self.completion_options) if self.completion_options else {}
        kwargs["model"] = self.model
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.aws_region_name:
            kwargs["aws_region_name"] = self.aws_region_name
        return kwargs


class ProfileReportModelConfig:
    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        config: Mapping[str, Any] | None = None,
    ):
        self.environ = environ if environ is not None else os.environ
        self.config = dict(config) if config is not None else _load_llm_config(
            self.environ.get("LLM_CONFIG_FILE")
        )

    def resolve(self) -> ProfileReportModelSettings:
        model = (
            self.environ.get("PROFILE_REPORT_MODEL")
            or _config_get(self.config, "profile_report", "model", PROFILE_REPORT_MODEL)
        )
        completion_options = _config_section(self.config, "completion")
        completion_options.setdefault("timeout", DEFAULT_LLM_TIMEOUT_SECONDS)
        if model.startswith("bedrock/") or model.startswith("amazon/"):
            return ProfileReportModelSettings(
                model=model,
                aws_region_name=self.environ.get("AWS_REGION")
                or self.environ.get("AWS_DEFAULT_REGION")
                or _config_get(self.config, "aws", "region"),
                completion_options=completion_options,
            )
        api_key = _resolve_api_key(model, self.environ)
        if not api_key:
            raise ValueError(
                "No API key configured for the selected PROFILE_REPORT_MODEL. Set OPENAI_API_KEY, "
                "GOOGLE_API_KEY, or LITELLM_API_KEY."
            )
        return ProfileReportModelSettings(
            model=model,
            api_key=api_key,
            api_base=self.environ.get("LITELLM_BASE_URL")
            or _config_get(self.config, "litellm", "api_base"),
            completion_options=completion_options,
        )


class ProfileReportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1)
    overall_summary: str = Field(min_length=1)
    recurring_gaps: list[str] = Field(default_factory=list)
    broader_related_patterns: list[str] = Field(default_factory=list)
    chapter_topic_weakness_map: list[str] = Field(default_factory=list)
    isolated_gaps: list[str] = Field(default_factory=list)
    study_priorities: list[str] = Field(default_factory=list)
    teacher_intervention_notes: list[str] = Field(default_factory=list)
    evidence_appendix: list[str] = Field(default_factory=list)

    @field_validator("*", mode="before")
    @classmethod
    def reject_blank_strings(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("Profile report text must not be blank.")
        return value


class ProfileReportWriter(Protocol):
    def write(self, evidence_pack: LongitudinalEvidencePack) -> ProfileReportOutput:
        """Create an interpreted written profile from validated evidence."""


class LiteLLMProfileReportWriter:
    def __init__(
        self,
        *,
        model_config: ProfileReportModelConfig | None = None,
        completion_fn: CompletionFunction | None = None,
    ):
        self.model_config = model_config or ProfileReportModelConfig()
        self.completion_fn = completion_fn or completion

    def write(self, evidence_pack: LongitudinalEvidencePack) -> ProfileReportOutput:
        model_settings = self.model_config.resolve()
        response = self.completion_fn(
            **model_settings.to_litellm_kwargs(),
            messages=[
                {
                    "role": "system",
                    "content": _profile_report_system_prompt(),
                },
                {
                    "role": "user",
                    "content": _profile_report_user_prompt(evidence_pack),
                },
            ],
            response_format=profile_report_response_format(),
            caching=False,
            cache={"no-cache": True},
            num_retries=0,
        )
        content = response["choices"][0]["message"]["content"].strip()
        return ProfileReportOutput.model_validate_json(content)


class ProfileAnalysisService:
    def __init__(self, report_writer: ProfileReportWriter | None = None):
        self.report_writer = report_writer

    def generate(self, evidence_pack: LongitudinalEvidencePack) -> ProfileReportOutput:
        if self.report_writer is not None:
            try:
                report = self.report_writer.write(evidence_pack)
                validate_profile_report(report, evidence_pack)
                return report
            except Exception as exc:
                logger.warning(
                    "profile_report_llm_failed fallback=deterministic error_type=%s error=%s",
                    exc.__class__.__name__,
                    exc or "[no message]",
                    exc_info=True,
                )
        return self._deterministic_report(evidence_pack)

    def _deterministic_report(
        self,
        evidence_pack: LongitudinalEvidencePack,
    ) -> ProfileReportOutput:
        recurring = [
            cluster
            for cluster in evidence_pack.clusters
            if cluster.recurrence_label == "recurring"
        ]
        isolated = [
            cluster
            for cluster in evidence_pack.clusters
            if cluster.recurrence_label != "recurring"
        ]
        recurring_lines = [
            (
                f"{cluster.cluster.title}: supported by {cluster.diagnosis_report_count} "
                f"diagnosis reports and {cluster.question_count} questions."
            )
            for cluster in recurring
        ]
        isolated_lines = [
            (
                f"{cluster.cluster.title}: isolated or early indicator from "
                f"{cluster.diagnosis_report_count} diagnosis report."
            )
            for cluster in isolated
        ]
        return ProfileReportOutput(
            subject=evidence_pack.subject,
            overall_summary=_overall_summary(evidence_pack),
            recurring_gaps=recurring_lines,
            broader_related_patterns=[
                cluster.cluster.title
                for cluster in recurring
                if cluster.cluster.cluster_type == "related_distinct_subgaps"
            ],
            chapter_topic_weakness_map=_chapter_topic_lines(evidence_pack),
            isolated_gaps=isolated_lines,
            study_priorities=_study_priorities(recurring_lines, isolated_lines),
            teacher_intervention_notes=_teacher_notes(recurring_lines, isolated_lines),
            evidence_appendix=_evidence_appendix(evidence_pack),
        )

    @staticmethod
    def render_markdown(report: ProfileReportOutput) -> str:
        sections = [
            ("Overall Summary", [report.overall_summary]),
            ("Recurring Gaps", report.recurring_gaps or ["No recurring gaps yet."]),
            ("Broader Related Patterns", report.broader_related_patterns or ["No broader recurring patterns yet."]),
            ("Chapter/Topic Weakness Map", report.chapter_topic_weakness_map or ["No chapter/topic weakness map yet."]),
            ("Isolated Or Early Indicators", report.isolated_gaps or ["No isolated gaps yet."]),
            ("Study Priorities", report.study_priorities or ["Continue collecting diagnosis history."]),
            ("Teacher Intervention Notes", report.teacher_intervention_notes or ["Monitor future diagnosis reports."]),
            ("Evidence Appendix", report.evidence_appendix or ["No evidence references available."]),
        ]
        lines = [f"# {report.subject} Longitudinal Profile"]
        for title, items in sections:
            lines.append(f"\n## {title}")
            for item in items:
                lines.append(f"- {item}")
        return "\n".join(lines)


def validate_profile_report(report: ProfileReportOutput, evidence_pack: LongitudinalEvidencePack) -> None:
    recurring_cluster_ids = {
        cluster.cluster.cluster_id
        for cluster in evidence_pack.clusters
        if cluster.recurrence_label == "recurring"
    }
    if not recurring_cluster_ids and any("recurring" in line.casefold() for line in report.recurring_gaps):
        raise ValueError("Profile report contains unsupported recurring claims.")
    evidence_ids = set(evidence_pack.evidence_index)
    appendix_text = "\n".join(report.evidence_appendix)
    missing = [evidence_id for evidence_id in evidence_ids if evidence_id not in appendix_text]
    if missing:
        raise ValueError("Profile report evidence appendix is missing evidence references.")
    if report.subject != evidence_pack.subject:
        raise ValueError("Profile report subject does not match evidence pack.")


def profile_report_response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": PROFILE_REPORT_SCHEMA_NAME,
            "strict": True,
            "schema": ProfileReportOutput.model_json_schema(),
        },
    }


def build_profile_analysis_service_from_environment(
    environ: Mapping[str, str] | None = None,
) -> ProfileAnalysisService:
    resolved_environ = environ if environ is not None else os.environ
    if not _profile_report_llm_enabled(resolved_environ):
        return ProfileAnalysisService()
    return ProfileAnalysisService(
        report_writer=LiteLLMProfileReportWriter(
            model_config=ProfileReportModelConfig(environ=resolved_environ),
        )
    )


def _profile_report_llm_enabled(environ: Mapping[str, str]) -> bool:
    value = environ.get("PROFILE_REPORT_LLM_ENABLED")
    if value is None:
        return True
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_llm_config(path: str | None = None) -> dict[str, Any]:
    config_path = _resolve_config_path(path)
    if not config_path:
        return {}
    with config_path.open("rb") as config_file:
        return tomllib.load(config_file)


def _resolve_config_path(path: str | None) -> Path | None:
    candidates = (Path(path),) if path else DEFAULT_CONFIG_PATHS
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _config_get(
    config: Mapping[str, Any],
    section: str,
    key: str,
    default: Any = None,
) -> Any:
    value = _config_section(config, section).get(key)
    return value if value not in (None, "") else default


def _config_section(config: Mapping[str, Any], section: str) -> dict[str, Any]:
    current: Any = config
    for part in section.split("."):
        if not isinstance(current, Mapping):
            return {}
        current = current.get(part, {})
    return deepcopy(current) if isinstance(current, Mapping) else {}


def _resolve_api_key(model: str, environ: Mapping[str, str]) -> str | None:
    if model.startswith("openai/"):
        return environ.get("OPENAI_API_KEY") or environ.get("LITELLM_API_KEY")
    if model.startswith("gemini/") or model.startswith("google/"):
        return environ.get("GOOGLE_API_KEY") or environ.get("LITELLM_API_KEY")
    return environ.get("LITELLM_API_KEY")


def _profile_report_system_prompt() -> str:
    return (
        "You write concise longitudinal JEE student profile reports for students and teachers. "
        "Use only the supplied evidence pack. Do not invent tests, questions, chapters, topics, "
        "or recurrence claims. Return JSON only, matching the provided schema. The evidence "
        "appendix must mention every evidence id exactly as provided."
    )


def _profile_report_user_prompt(evidence_pack: LongitudinalEvidencePack) -> str:
    return (
        "Interpret this validated longitudinal evidence pack into a readable profile report. "
        "Keep each list item specific, evidence-backed, and useful for study planning. "
        "Recurring gaps may only come from clusters whose recurrence_label is recurring. "
        "Use isolated_gaps for one-off or early-indicator clusters.\n\n"
        f"{json.dumps(_profile_report_payload(evidence_pack), sort_keys=True)}"
    )


def _profile_report_payload(evidence_pack: LongitudinalEvidencePack) -> dict[str, Any]:
    return evidence_pack.model_dump(mode="json")


def _overall_summary(evidence_pack: LongitudinalEvidencePack) -> str:
    return (
        f"Analyzed {evidence_pack.question_count} diagnosed questions from "
        f"{evidence_pack.diagnosis_report_count} diagnosis reports for {evidence_pack.subject}."
    )


def _chapter_topic_lines(evidence_pack: LongitudinalEvidencePack) -> list[str]:
    return [
        (
            f"{entry.chapter} / {entry.topic}: recurring={len(entry.recurring_cluster_ids)}, "
            f"isolated_or_early={len(entry.isolated_cluster_ids)}"
        )
        for entry in evidence_pack.chapter_topic_map
    ]


def _study_priorities(recurring: list[str], isolated: list[str]) -> list[str]:
    if recurring:
        return [f"Prioritize recurring gap: {line}" for line in recurring]
    return [f"Treat as early indicator: {line}" for line in isolated]


def _teacher_notes(recurring: list[str], isolated: list[str]) -> list[str]:
    if recurring:
        return [f"Reteach and drill: {line}" for line in recurring]
    return [f"Monitor before calling this recurring: {line}" for line in isolated]


def _evidence_appendix(evidence_pack: LongitudinalEvidencePack) -> list[str]:
    return [
        (
            f"{evidence.evidence_id}: report={evidence.diagnosis_report_id}, "
            f"question={evidence.question_number}, chapter={evidence.chapter}, topic={evidence.topic}"
        )
        for evidence in evidence_pack.evidence_index.values()
    ]
