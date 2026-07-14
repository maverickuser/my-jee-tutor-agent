import json
from pathlib import Path
import tempfile
import unittest

from jee_tutor.agent.diagnosis_output import DiagnosisResponse
from jee_tutor.curriculum.loader import CurriculumTaxonomyConfig, CurriculumTaxonomyLoader
from jee_tutor.curriculum.taxonomy import CurriculumTaxonomy
from jee_tutor.curriculum.validator import CurriculumValidator, normalize_label
from tests.agent.test_diagnosis_output import question


def taxonomy_payload():
    return {
        "version": "2026-01",
        "source_documents": [{"subject": "Physics", "uri": "s3://bucket/physics.pdf"}],
        "subjects": {
            "Physics": {
                "chapters": {
                    "Electrostatics": {
                        "aliases": ["Electric Charges"],
                        "topics": {
                            "Capacitance": {"aliases": ["Capacitors"]},
                            "Electric Field": {"aliases": []},
                            "Dielectrics and polarization": {"aliases": []},
                        },
                    },
                    "Mechanics": {
                        "aliases": [],
                        "topics": {
                            "Newton Laws": {"aliases": ["Laws of Motion"]},
                        },
                    },
                }
            },
            "Chemistry": {
                "chapters": {
                    "Some Basic Principles of Organic Chemistry": {
                        "aliases": ["General Organic Chemistry", "GOC"],
                        "topics": {
                            "Free radicals, carbocations and carbanions": {"aliases": []},
                        },
                    },
                    "Organic Compounds Containing Oxygen": {
                        "aliases": ["Alcohols Phenols and Ethers"],
                        "topics": {
                            "Structure of ethers": {"aliases": []},
                            "C-O bond cleavage reactions of ethers": {"aliases": []},
                        },
                    },
                }
            },
            "Mathematics": {
                "chapters": {
                    "Limit, Continuity and Differentiability": {
                        "aliases": ["Application of Derivatives"],
                        "topics": {
                            "Polynomial, rational, trigonometric, logarithmic and exponential functions": {
                                "aliases": []
                            },
                            "Increasing and decreasing functions": {
                                "aliases": ["Monotonic functions"]
                            },
                        },
                    },
                }
            },
        },
    }


def diagnosis(**overrides):
    return DiagnosisResponse.model_validate({"questions": [question(**overrides)]})


class Body:
    def __init__(self, data: bytes):
        self.data = data

    def read(self):
        return self.data


class FakeS3:
    def __init__(self, payload: dict):
        self.payload = payload
        self.etag = "v1"
        self.head_calls = 0
        self.get_calls = 0

    def head_object(self, **kwargs):
        self.head_calls += 1
        return {"ETag": self.etag}

    def get_object(self, **kwargs):
        self.get_calls += 1
        return {"Body": Body(json.dumps(self.payload).encode("utf-8"))}


class CurriculumTaxonomyTest(unittest.TestCase):
    def test_taxonomy_schema_requires_subjects_chapters_and_topics(self):
        parsed = CurriculumTaxonomy.model_validate(taxonomy_payload())

        self.assertEqual(parsed.version, "2026-01")
        self.assertEqual(parsed.subjects["Physics"].chapters["Electrostatics"].aliases, ["Electric Charges"])
        with self.assertRaises(ValueError):
            CurriculumTaxonomy.model_validate({"version": "x", "source_documents": [], "subjects": {}})

    def test_normalization_handles_case_whitespace_punctuation_and_ampersand(self):
        self.assertEqual(normalize_label("  Work & Energy!! "), "work and energy")

    def test_validator_accepts_canonical_and_alias_labels(self):
        validator = CurriculumValidator(CurriculumTaxonomy.model_validate(taxonomy_payload()))

        self.assertTrue(validator.validate(diagnosis()).valid)
        self.assertTrue(
            validator.validate(
                diagnosis(chapter=" electric charges ", topic="capacitors")
            ).valid
        )

    def test_validator_accepts_composite_topic_words_within_same_chapter(self):
        validator = CurriculumValidator(CurriculumTaxonomy.model_validate(taxonomy_payload()))

        self.assertTrue(
            validator.validate(
                diagnosis(chapter="Electrostatics", topic="Capacitors and Dielectrics")
            ).valid
        )
        self.assertEqual(
            validator.validate(
                diagnosis(chapter="Electrostatics", topic="Thermodynamic Entropy")
            ).category,
            "unknown_topic",
        )

    def test_validator_accepts_partial_chapter_and_topic_words(self):
        validator = CurriculumValidator(CurriculumTaxonomy.model_validate(taxonomy_payload()))

        self.assertTrue(
            validator.validate(
                diagnosis(chapter="Organic Chemistry", topic="Carbocations")
            ).valid
        )
        self.assertTrue(
            validator.validate(
                diagnosis(
                    chapter="Organic Chemistry - Ethers",
                    topic="Acid-Catalyzed Ether Cleavage and Carbocation Reactions",
                )
            ).valid
        )

    def test_validator_accepts_strong_partial_topic_match_across_syllabus(self):
        validator = CurriculumValidator(CurriculumTaxonomy.model_validate(taxonomy_payload()))

        self.assertTrue(
            validator.validate(
                diagnosis(
                    chapter="Application of Derivatives",
                    topic="Properties of Polynomial Functions",
                )
            ).valid
        )
        self.assertTrue(
            validator.validate(
                diagnosis(
                    chapter="Application of Derivatives",
                    topic="Monotonicity of Functions",
                )
            ).valid
        )

    def test_validator_accepts_ambiguous_partial_topic_match_across_syllabus(self):
        payload = taxonomy_payload()
        payload["subjects"]["Mathematics"]["chapters"]["Functions"] = {
            "aliases": [],
            "topics": {
                "Polynomial functions and equations": {"aliases": []},
            },
        }
        validator = CurriculumValidator(CurriculumTaxonomy.model_validate(payload))

        self.assertTrue(
            validator.validate(
                diagnosis(
                    chapter="Electrostatics",
                    topic="Properties of Polynomial Functions",
                )
            ).valid
        )

    def test_validator_rejects_unknown_and_wrong_pairs(self):
        validator = CurriculumValidator(CurriculumTaxonomy.model_validate(taxonomy_payload()))

        self.assertEqual(
            validator.validate(diagnosis(chapter="Unknown", topic="Capacitance")).category,
            "unknown_chapter",
        )
        self.assertEqual(
            validator.validate(diagnosis(chapter="Electrostatics", topic="Unknown")).category,
            "unknown_topic",
        )
        unknown_topic = validator.validate(diagnosis(chapter="Electrostatics", topic="Unknown"))
        self.assertEqual(
            unknown_topic.details,
            {
                "question_number": "6",
                "chapter": "Electrostatics",
                "topic": "Unknown",
                "normalized_chapter": "electrostatics",
                "normalized_topic": "unknown",
                "taxonomy_version": "2026-01",
            },
        )
        self.assertTrue(
            validator.validate(diagnosis(chapter="Electrostatics", topic="Newton Laws")).valid
        )

    def test_validator_handles_unable_to_determine_sentinel(self):
        validator = CurriculumValidator(CurriculumTaxonomy.model_validate(taxonomy_payload()))

        valid = validator.validate(
            diagnosis(
                chapter="Unable to determine from image",
                topic="Unable to determine from image",
            )
        )
        self.assertTrue(valid.valid)
        self.assertEqual(valid.low_confidence_count, 1)
        self.assertEqual(
            validator.validate(
                diagnosis(chapter="Unable to determine from image", topic="Capacitance")
            ).category,
            "partial_curriculum_label",
        )

    def test_validator_rejects_ambiguous_chapter_topic(self):
        payload = taxonomy_payload()
        payload["subjects"]["Mathematics"] = {
            "chapters": {
                "Electrostatics": {
                    "aliases": [],
                    "topics": {"Capacitance": {"aliases": []}},
                }
            }
        }
        validator = CurriculumValidator(CurriculumTaxonomy.model_validate(payload))

        self.assertEqual(validator.validate(diagnosis()).category, "ambiguous_chapter_topic")

    def test_local_loader_uses_cache_before_ttl_and_reloads_after_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "taxonomy.json"
            path.write_text(json.dumps(taxonomy_payload()), encoding="utf-8")
            ticks = iter([0, 10, 4000, 4001])
            loader = CurriculumTaxonomyLoader(
                config=CurriculumTaxonomyConfig(local_path=str(path), cache_ttl_seconds=100),
                monotonic=lambda: next(ticks),
            )

            self.assertEqual(loader.load().version, "2026-01")
            self.assertEqual(loader.load().version, "2026-01")
            updated = taxonomy_payload()
            updated["version"] = "2026-02"
            path.write_text(json.dumps(updated), encoding="utf-8")
            self.assertEqual(loader.load().version, "2026-02")

    def test_s3_loader_uses_head_before_refetching_unchanged_object(self):
        fake_s3 = FakeS3(taxonomy_payload())
        ticks = iter([0, 10, 4000, 4001])
        loader = CurriculumTaxonomyLoader(
            config=CurriculumTaxonomyConfig(
                s3_uri="s3://bucket/taxonomy.json",
                cache_ttl_seconds=100,
            ),
            s3_client=fake_s3,
            monotonic=lambda: next(ticks),
        )

        self.assertEqual(loader.load().version, "2026-01")
        self.assertEqual(loader.load().version, "2026-01")
        self.assertEqual(fake_s3.head_calls, 1)
        self.assertEqual(fake_s3.get_calls, 1)
        self.assertEqual(loader.load().version, "2026-01")
        self.assertEqual(fake_s3.head_calls, 2)
        self.assertEqual(fake_s3.get_calls, 1)

    def test_s3_loader_reloads_when_etag_changes(self):
        fake_s3 = FakeS3(taxonomy_payload())
        ticks = iter([0, 4000, 4001])
        loader = CurriculumTaxonomyLoader(
            config=CurriculumTaxonomyConfig(
                s3_uri="s3://bucket/taxonomy.json",
                cache_ttl_seconds=100,
            ),
            s3_client=fake_s3,
            monotonic=lambda: next(ticks),
        )

        self.assertEqual(loader.load().version, "2026-01")
        fake_s3.etag = "v2"
        fake_s3.payload = taxonomy_payload()
        fake_s3.payload["version"] = "2026-02"

        self.assertEqual(loader.load().version, "2026-02")
        self.assertEqual(fake_s3.get_calls, 2)

    def test_loader_fail_open_and_fail_closed_without_source(self):
        self.assertIsNone(CurriculumTaxonomyLoader(config=CurriculumTaxonomyConfig()).load())
        with self.assertRaisesRegex(RuntimeError, "taxonomy_unavailable"):
            CurriculumTaxonomyLoader(
                config=CurriculumTaxonomyConfig(required=True)
            ).load()

    def test_loader_keeps_prior_valid_cache_when_reload_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "taxonomy.json"
            path.write_text(json.dumps(taxonomy_payload()), encoding="utf-8")
            ticks = iter([0, 10, 4000, 4001])
            loader = CurriculumTaxonomyLoader(
                config=CurriculumTaxonomyConfig(local_path=str(path), cache_ttl_seconds=100),
                monotonic=lambda: next(ticks),
            )
            self.assertEqual(loader.load().version, "2026-01")
            path.write_text("{bad", encoding="utf-8")

            self.assertEqual(loader.load().version, "2026-01")


if __name__ == "__main__":
    unittest.main()
