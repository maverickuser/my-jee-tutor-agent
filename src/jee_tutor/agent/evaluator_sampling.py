import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from jee_tutor.agent.config_loader import LLMConfig


class EvaluatorMode(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    GATED = "gated"


@dataclass(frozen=True)
class EvaluatorSamplingPolicy:
    enabled: bool = True
    sample_rate: float = 1.0
    mode: EvaluatorMode = EvaluatorMode.GATED

    def __post_init__(self) -> None:
        if not 0.0 <= self.sample_rate <= 1.0:
            raise ValueError("Final evaluator sample_rate must be from 0.0 to 1.0.")

    @classmethod
    def from_config(cls, config: LLMConfig | None = None) -> "EvaluatorSamplingPolicy":
        loaded = config or LLMConfig.load()
        return cls(
            enabled=bool(loaded.get("final_evaluator", "enabled", False)),
            sample_rate=float(loaded.get("final_evaluator", "sample_rate", 0.0)),
            mode=EvaluatorMode(loaded.get("final_evaluator", "mode", "disabled")),
        )

    def selected(
        self,
        *,
        idempotency_key: str | None,
        canonical_payload: dict[str, Any],
    ) -> bool:
        if not self.enabled or self.mode == EvaluatorMode.DISABLED or self.sample_rate == 0.0:
            return False
        if self.sample_rate == 1.0:
            return True
        stable_key = idempotency_key or hashlib.sha256(
            json.dumps(
                canonical_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode()
        ).hexdigest()
        bucket = int.from_bytes(hashlib.sha256(stable_key.encode()).digest()[:8], "big")
        return bucket / 2**64 < self.sample_rate
