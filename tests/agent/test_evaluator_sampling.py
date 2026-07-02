import unittest

from jee_tutor.agent.evaluator_sampling import EvaluatorMode, EvaluatorSamplingPolicy


class EvaluatorSamplingTest(unittest.TestCase):
    def test_boundaries_and_stability(self):
        payload = {"task": "x", "image": "redacted"}
        self.assertFalse(
            EvaluatorSamplingPolicy(sample_rate=0).selected(
                idempotency_key=None,
                canonical_payload=payload,
            )
        )
        self.assertTrue(
            EvaluatorSamplingPolicy(sample_rate=1).selected(
                idempotency_key=None,
                canonical_payload=payload,
            )
        )
        policy = EvaluatorSamplingPolicy(sample_rate=0.5, mode=EvaluatorMode.SHADOW)
        first = policy.selected(idempotency_key="stable-key", canonical_payload=payload)
        self.assertEqual(
            first,
            policy.selected(idempotency_key="stable-key", canonical_payload={"different": True}),
        )

    def test_invalid_rate_fails(self):
        with self.assertRaises(ValueError):
            EvaluatorSamplingPolicy(sample_rate=1.1)
