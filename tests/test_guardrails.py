import base64
import unittest

from agents.tutor_agent.guardrails import GuardrailSettings, RuntimeGuardrail


class FakeBedrockRuntimeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def apply_guardrail(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class RuntimeGuardrailTest(unittest.TestCase):
    def test_disabled_guardrail_allows_without_calling_bedrock(self):
        client = FakeBedrockRuntimeClient({"action": "GUARDRAIL_INTERVENED"})
        guardrail = RuntimeGuardrail(
            settings=GuardrailSettings(enabled=False, identifier="guardrail-id"),
            client=client,
        )

        result = guardrail.check_output("blocked-looking output")

        self.assertTrue(result.allowed)
        self.assertEqual(client.calls, [])

    def test_input_guardrail_sends_text_and_png_image(self):
        client = FakeBedrockRuntimeClient({"action": "NONE"})
        guardrail = RuntimeGuardrail(
            settings=GuardrailSettings(enabled=True, identifier="guardrail-id", version="1"),
            client=client,
        )
        image_bytes = b"fake-png-bytes"
        image_data_uri = "data:image/png;base64," + base64.b64encode(image_bytes).decode()

        result = guardrail.check_input(
            question_context="Please check this attempt.",
            image_data_uri=image_data_uri,
        )

        self.assertTrue(result.allowed)
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["guardrailIdentifier"], "guardrail-id")
        self.assertEqual(call["guardrailVersion"], "1")
        self.assertEqual(call["source"], "INPUT")
        self.assertEqual(call["content"][0], {"text": {"text": "Please check this attempt."}})
        self.assertEqual(
            call["content"][1],
            {"image": {"format": "png", "source": {"bytes": image_bytes}}},
        )

    def test_input_guardrail_sends_multiple_images(self):
        client = FakeBedrockRuntimeClient({"action": "NONE"})
        guardrail = RuntimeGuardrail(
            settings=GuardrailSettings(enabled=True, identifier="guardrail-id", version="1"),
            client=client,
        )
        png_bytes = b"fake-png-bytes"
        jpeg_bytes = b"fake-jpeg-bytes"
        image_data_uris = [
            "data:image/png;base64," + base64.b64encode(png_bytes).decode(),
            "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode(),
        ]

        result = guardrail.check_input(
            question_context="Please check this attempt.",
            image_data_uris=image_data_uris,
        )

        self.assertTrue(result.allowed)
        self.assertEqual(
            client.calls[0]["content"],
            [
                {"text": {"text": "Please check this attempt."}},
                {"image": {"format": "png", "source": {"bytes": png_bytes}}},
                {"image": {"format": "jpeg", "source": {"bytes": jpeg_bytes}}},
            ],
        )

    def test_output_intervention_returns_guardrail_message(self):
        client = FakeBedrockRuntimeClient(
            {
                "action": "GUARDRAIL_INTERVENED",
                "actionReason": "Denied topic",
                "outputs": [{"text": "I cannot help with that request."}],
            }
        )
        guardrail = RuntimeGuardrail(
            settings=GuardrailSettings(enabled=True, identifier="guardrail-id"),
            client=client,
        )

        result = guardrail.check_output("unsafe output")

        self.assertFalse(result.allowed)
        self.assertEqual(result.message, "I cannot help with that request.")
        self.assertEqual(result.action_reason, "Denied topic")

    def test_pii_intervention_returns_non_leaking_detection_details(self):
        client = FakeBedrockRuntimeClient(
            {
                "action": "GUARDRAIL_INTERVENED",
                "assessments": [
                    {
                        "sensitiveInformationPolicy": {
                            "piiEntities": [
                                {
                                    "type": "EMAIL",
                                    "match": "student@example.com",
                                    "action": "BLOCKED",
                                },
                                {
                                    "type": "PHONE",
                                    "match": "+91 99999 99999",
                                    "action": "ANONYMIZED",
                                },
                                {
                                    "type": "NAME",
                                    "match": "Aarav",
                                    "action": "NONE",
                                },
                            ],
                            "regexes": [
                                {
                                    "name": "school_roll_number",
                                    "match": "JEE-2026-123",
                                    "action": "BLOCKED",
                                }
                            ],
                        }
                    }
                ],
            }
        )
        guardrail = RuntimeGuardrail(
            settings=GuardrailSettings(enabled=True, identifier="guardrail-id"),
            client=client,
        )

        result = guardrail.check_input(
            question_context="My email is student@example.com.",
        )

        self.assertFalse(result.allowed)
        self.assertEqual(
            result.message,
            "Request blocked because it contains sensitive personal information.",
        )
        self.assertEqual(result.detected_pii, ["EMAIL", "PHONE", "school_roll_number"])
        self.assertEqual(
            result.action_reason,
            "Sensitive information detected: EMAIL, PHONE, school_roll_number",
        )
        self.assertNotIn("student@example.com", result.action_reason)

    def test_configured_failure_fails_closed(self):
        client = FakeBedrockRuntimeClient(RuntimeError("bedrock unavailable"))
        guardrail = RuntimeGuardrail(
            settings=GuardrailSettings(
                enabled=True,
                identifier="guardrail-id",
                fail_closed=True,
            ),
            client=client,
        )

        result = guardrail.check_output("analysis")

        self.assertFalse(result.allowed)
        self.assertEqual(result.message, "Runtime guardrail check failed.")
        self.assertIn("bedrock unavailable", result.action_reason)

    def test_configured_failure_can_fail_open(self):
        client = FakeBedrockRuntimeClient(RuntimeError("bedrock unavailable"))
        guardrail = RuntimeGuardrail(
            settings=GuardrailSettings(
                enabled=True,
                identifier="guardrail-id",
                fail_closed=False,
            ),
            client=client,
        )

        result = guardrail.check_output("analysis")

        self.assertTrue(result.allowed)
        self.assertIn("bedrock unavailable", result.action_reason)


if __name__ == "__main__":
    unittest.main()
