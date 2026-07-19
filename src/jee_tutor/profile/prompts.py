from __future__ import annotations

import json
from typing import Any

from jee_tutor.profile.semantic import LongitudinalEvidencePack


def profile_report_system_prompt() -> str:
    return (
        "You are an expert educational diagnostician with deep knowledge of curriculum standards "
        "and cognitive learning science. You write concise longitudinal JEE student profile "
        "reports for students and teachers.\n\n"
        "Strict Operational Rules:\n\n"
        "1. Zero Hallucination: Use ONLY the supplied evidence pack. Do not invent tests, "
        "questions, chapters, topics, or recurrence claims.\n"
        "2. JSON Only: Return JSON only, perfectly matching the provided schema. Do not output "
        "any conversational text.\n"
        "3. Evidence Processing: The evidence appendix must mention every `evidence_reference` "
        "exactly as provided in the input. Do not expose opaque internal evidence IDs as "
        "human-facing references.\n"
        "4. Citation of Gaps: Recurring gap entries must explicitly cite the clustered "
        "`evidence_reference` values that support that specific gap.\n"
        "5. Student Study Priorities: These must be actionable next study steps derived "
        "directly from `exact_concept_gap` and `deep_dive_recommendation`, not restatements "
        "of cluster titles. Collate the information to avoid repetition and include clear "
        "reasoning. Ensure it is highly actionable and easily comprehensible by students.\n"
        "6. Teacher Intervention Notes: Describe exactly what to reteach, drill, verify, or "
        "monitor using the `likely_thought` and `why_wrong` evidence. Do not just list "
        "chapter or topic names. These notes must be highly actionable and easily "
        "comprehensible by teachers."
    )


def profile_report_user_prompt(evidence_pack: LongitudinalEvidencePack) -> str:
    return (
        "Interpret this validated longitudinal evidence pack into a readable profile report.\n\n"
        "Keep each list item specific, evidence-backed, and useful for study planning.\n"
        "Recurring gaps may only come from clusters whose recurrence_label is recurring.\n"
        "Use isolated_gaps for one-off or early-indicator clusters.\n\n"
        "<evidence_pack>\n"
        f"{json.dumps(profile_report_payload(evidence_pack), sort_keys=True)}\n"
        "</evidence_pack>"
    )


def profile_report_payload(evidence_pack: LongitudinalEvidencePack) -> dict[str, Any]:
    return evidence_pack.model_dump(mode="json")
