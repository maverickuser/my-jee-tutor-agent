"""Vision diagnosis application helpers."""

from collections.abc import Callable


class VisionDiagnosisService:
    """Coordinate batched vision diagnosis through an injected analyzer.

    The CrewAI adapter owns tool lifecycle concerns; this service owns the
    provider-neutral batching contract used by that adapter.
    """

    def __init__(self, analyze_batch: Callable[[list[str], list[str | None] | None], str]):
        self._analyze_batch = analyze_batch

    def analyze(
        self,
        image_data_uris: list[str],
        *,
        expected_question_numbers: list[str | None] | None = None,
        max_images_per_call: int = 3,
    ) -> list[str]:
        if max_images_per_call < 1:
            raise ValueError("max_images_per_call must be at least 1")

        outputs: list[str] = []
        question_numbers = expected_question_numbers or []
        for start in range(0, len(image_data_uris), max_images_per_call):
            end = start + max_images_per_call
            batch_images = image_data_uris[start:end]
            batch_questions = question_numbers[start:end] or None
            outputs.append(self._analyze_batch(batch_images, batch_questions))
        return outputs


__all__ = ["VisionDiagnosisService"]
