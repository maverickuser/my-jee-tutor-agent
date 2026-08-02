"""Curriculum domain contract re-exports."""

from jee_tutor.curriculum.taxonomy import (
    CurriculumTaxonomy,
    CurriculumSubject as SubjectTaxonomy,
    CurriculumTopic as TaxonomyTopic,
)
from jee_tutor.curriculum.validator import (
    CurriculumValidationError,
    CurriculumValidator,
    CurriculumValidationResult as ValidationResult,
)

__all__ = [
    "CurriculumTaxonomy",
    "CurriculumValidationError",
    "CurriculumValidator",
    "SubjectTaxonomy",
    "TaxonomyTopic",
    "ValidationResult",
]
