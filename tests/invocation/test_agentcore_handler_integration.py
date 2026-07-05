import unittest
from unittest.mock import ANY, Mock, patch

from jee_tutor.agent.guardrails import GuardrailCheck
from jee_tutor.agent.output_validation import OutputValidationError
from jee_tutor.email.models import EmailDeliveryOutcome, EmailDeliveryStatus
from jee_tutor.handler import handle_tutor_invocation
from jee_tutor.invocation.image_inputs import ResolvedImage
from jee_tutor.invocation.models import AgentInvocationStatus, TutorInvocationPayload
from jee_tutor.invocation.service import TutorInvocationService


class FakeRuntimeGuardrail:
    def __init__(
        self,
        input_result=None,
        output_result=None,
        calls=None,
    ):
        self.input_result = input_result or GuardrailCheck(allowed=True)
        self.output_result = output_result or GuardrailCheck(allowed=True)
        self.calls = calls if calls is not None else []

    def check_input(self, **kwargs):
        self.calls.append(("input", kwargs))
        return self.input_result

    def check_output(self, analysis):
        self.calls.append(("output", analysis))
        return self.output_result


class FakeArtifactWriter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def write_for_invocation(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class FakeSpan:
    def __init__(self):
        self.outputs = []

    def update(self, *, output):
        self.outputs.append(output)


class FakeInvocationSpanContext:
    def __init__(self, span):
        self.span = span

    def __enter__(self):
        return self.span

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeObservability:
    def __init__(self):
        self.span = FakeSpan()
        self.calls = []

    def invocation_span(self, **kwargs):
        self.calls.append(kwargs)
        return FakeInvocationSpanContext(self.span)


def resolved_image(data_uri="data:image/png;base64,ZmFrZQ==", question_number=None):
    return ResolvedImage(
        data_uri=data_uri,
        file_name=f"Question_{question_number}.png" if question_number else None,
        question_number=question_number,
    )


class AgentCoreHandlerIntegrationTest(unittest.TestCase):
    def test_idempotency_completed_replays_stored_response(self):
        image_resolver = Mock()
        idempotency_store = Mock()
        idempotency_store.claim.return_value = Mock(
            status="completed",
            response={"analysis": "cached"},
        )
        status_store = Mock()
        service = TutorInvocationService(
            image_resolver=image_resolver,
            guardrail=FakeRuntimeGuardrail(),
            workflow=Mock(),
            artifact_writer=FakeArtifactWriter(),
            idempotency_store=idempotency_store,
            status_store=status_store,
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                "idempotency_key": "attempt-123",
            }
        )

        self.assertEqual(response, {"analysis": "cached"})
        image_resolver.resolve_images.assert_not_called()
        service.workflow.assert_not_called()
        idempotency_store.complete.assert_not_called()
        status_store.upsert_invocation.assert_called()
        status_store.update_invocation.assert_called_once()

    def test_idempotency_in_progress_returns_blocked_error(self):
        image_resolver = Mock()
        idempotency_store = Mock()
        idempotency_store.claim.return_value = Mock(status="in_progress")
        status_store = Mock()
        service = TutorInvocationService(
            image_resolver=image_resolver,
            guardrail=FakeRuntimeGuardrail(),
            workflow=Mock(),
            artifact_writer=FakeArtifactWriter(),
            idempotency_store=idempotency_store,
            status_store=status_store,
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                "idempotency_key": "attempt-123",
            }
        )

        self.assertEqual(response["error"], "Tutor invocation is already in progress.")
        self.assertIn("Retry later", response["details"][0])
        service.workflow.assert_not_called()
        image_resolver.resolve_images.assert_not_called()
        status_store.update_invocation.assert_not_called()
        status_store.upsert_invocation.assert_called()

    def test_idempotency_conflict_returns_blocked_error(self):
        image_resolver = Mock()
        idempotency_store = Mock()
        idempotency_store.claim.return_value = Mock(status="conflict")
        status_store = Mock()
        service = TutorInvocationService(
            image_resolver=image_resolver,
            guardrail=FakeRuntimeGuardrail(),
            workflow=Mock(),
            artifact_writer=FakeArtifactWriter(),
            idempotency_store=idempotency_store,
            status_store=status_store,
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                "idempotency_key": "attempt-123",
            }
        )

        self.assertEqual(
            response["error"],
            "Idempotency key was already used with a different payload.",
        )
        self.assertIn("Use a new idempotency_key", response["details"][0])
        service.workflow.assert_not_called()
        image_resolver.resolve_images.assert_not_called()
        status_store.upsert_invocation.assert_called()

    def test_image_resolution_value_error_returns_invalid_payload_error(self):
        image_resolver = Mock()
        image_resolver.resolve_images.side_effect = ValueError("bad prefix")
        service = TutorInvocationService(
            image_resolver=image_resolver,
            guardrail=FakeRuntimeGuardrail(),
            workflow=Mock(),
            artifact_writer=FakeArtifactWriter(),
        )

        response = service.handle(
            {
                "image_s3_prefix": "s3://attempt-bucket/maths/",
            }
        )

        self.assertEqual(response["error"], "Invalid tutor invocation payload.")
        self.assertIn("bad prefix", response["details"])
        service.workflow.assert_not_called()

    def test_artifact_writer_failure_keeps_analysis_and_records_error(self):
        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **_: "analysis markdown",
            artifact_writer=FakeArtifactWriter(error=RuntimeError("no tex")),
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                "save_analysis_pdf": True,
            }
        )

        self.assertEqual(response["analysis"], "analysis markdown")
        self.assertIn("artifact_errors", response)
        self.assertTrue(
            any("Failed to write analysis artifacts: RuntimeError: no tex" == item for item in response["artifact_errors"])
        )

    def test_email_delivery_missing_pdf_returns_failure_status(self):
        from jee_tutor.artifacts.writer import AnalysisArtifactResult

        image_resolver = Mock()
        image_resolver.resolve_images.return_value = [resolved_image()]
        email_coordinator = Mock()
        service = TutorInvocationService(
            image_resolver=image_resolver,
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **_: "analysis markdown",
            artifact_writer=FakeArtifactWriter(AnalysisArtifactResult()),
            email_coordinator=email_coordinator,
        )

        response = service.handle(
            {
                "image_s3_prefix": "s3://attempt-bucket/maths/",
                "recipient_email": "student@example.com",
                "save_analysis_pdf": False,
            }
        )

        self.assertEqual(response["email_status"], "failed")
        self.assertIn("stored PDF artifact", response["email_error"])
        email_coordinator.request_delivery.assert_not_called()

    def test_email_delivery_runtime_exception_is_captured(self):
        from jee_tutor.artifacts.writer import AnalysisArtifactResult

        image_resolver = Mock()
        image_resolver.resolve_images.return_value = [resolved_image()]
        email_coordinator = Mock()
        email_coordinator.request_delivery.side_effect = RuntimeError("ses down")
        service = TutorInvocationService(
            image_resolver=image_resolver,
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **_: "analysis markdown",
            artifact_writer=FakeArtifactWriter(
                AnalysisArtifactResult(pdf_uri="s3://attempt-bucket/maths/report.pdf")
            ),
            email_coordinator=email_coordinator,
        )

        response = service.handle(
            {
                "image_s3_prefix": "s3://attempt-bucket/maths/",
                "recipient_email": "student@example.com",
                "save_analysis_pdf": False,
            }
        )

        self.assertEqual(response["email_status"], "failed")
        self.assertIn("RuntimeError: ses down", response["email_error"])
        email_coordinator.request_delivery.assert_called_once()

    def test_output_validation_error_details_are_preserved(self):
        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=Mock(side_effect=OutputValidationError("bad table", details=["missing header"])),
            artifact_writer=FakeArtifactWriter(),
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
            }
        )

        self.assertEqual(response["error"], "Tutor workflow failed while analyzing images.")
        self.assertIn("missing header", response["details"])

    def test_successful_span_is_updated_with_response(self):
        observability = FakeObservability()
        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            observability=observability,
            workflow=lambda **_: "analysis markdown",
            artifact_writer=FakeArtifactWriter(),
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
            }
        )

        self.assertEqual(response["analysis"], "analysis markdown")
        self.assertTrue(observability.calls)
        self.assertTrue(observability.span.outputs)
        self.assertEqual(observability.span.outputs[-1]["analysis"], "analysis markdown")

    def test_workflow_error_details_handles_empty_image_list(self):
        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=Mock(),
            artifact_writer=FakeArtifactWriter(),
        )
        invocation = TutorInvocationPayload.model_validate(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
            }
        )

        details = service._workflow_error_details(
            OutputValidationError("bad table", details=["missing header"]),
            [],
            invocation,
        )

        self.assertIn("Expected question numbers: [none].", details)
        self.assertIn("missing header", details)

    def test_record_invocation_noops_when_status_store_is_missing(self):
        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=Mock(),
            artifact_writer=FakeArtifactWriter(),
        )
        service.status_store = None
        invocation = TutorInvocationPayload.model_validate(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
            }
        )

        self.assertIsNone(
            service._record_invocation(
                invocation_id="inv-1",
                invocation=invocation,
                status=AgentInvocationStatus.RECEIVED,
            )
        )

    def test_successful_invocation_checks_guardrails_around_workflow(self):
        guardrail_calls = []

        with (
            patch(
                "jee_tutor.invocation.service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(calls=guardrail_calls),
            ),
            patch(
                "jee_tutor.invocation.service.run_tutor_workflow",
                return_value="coaching analysis",
            ) as run_tutor_workflow,
        ):
            response = handle_tutor_invocation(
                {
                    "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                    "task": "student context",
                }
            )

        self.assertEqual(response, {"analysis": "coaching analysis"})
        run_tutor_workflow.assert_called_once_with(
            image_data_uris=["data:image/png;base64,ZmFrZQ=="],
            question_context="student context",
            expected_question_numbers=[None],
            invocation_id=ANY,
            status_store=ANY,
        )
        self.assertEqual(
            guardrail_calls,
            [
                (
                    "input",
                    {
                        "question_context": "student context",
                        "image_data_uris": ["data:image/png;base64,ZmFrZQ=="],
                    },
                ),
                ("output", "coaching analysis"),
            ],
        )

    def test_agentcore_json_contract_uses_task_and_s3_fields(self):
        image_resolver = Mock()
        image_resolver.resolve_images.return_value = [resolved_image()]
        service = TutorInvocationService(
            image_resolver=image_resolver,
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **kwargs: kwargs["question_context"],
            artifact_writer=FakeArtifactWriter(),
        )

        response = service.handle(
            {
                "task": "diagnose maths attempt",
                "subject": "maths",
                "image_s3_prefix": "s3://attempt-bucket/maths/attempt-123/",
                "save_analysis_pdf": False,
            }
        )

        self.assertEqual(response, {"analysis": "diagnose maths attempt"})
        image_resolver.resolve_images.assert_called_once_with(
            image_data_uri=None,
            image_s3_prefix="s3://attempt-bucket/maths/attempt-123/",
        )

    def test_default_invocation_returns_workflow_analysis(self):
        workflow = Mock(return_value="baseline analysis")
        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=workflow,
            artifact_writer=FakeArtifactWriter(),
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                "save_analysis_pdf": False,
            }
        )

        self.assertEqual(response, {"analysis": "baseline analysis"})
        self.assertEqual(workflow.call_count, 1)

    def test_legacy_folder_invocation_is_rejected(self):
        response = handle_tutor_invocation(
            {
                "image_folder": "/app/input/attempt-images",
                "task": "multi-page attempt",
            }
        )

        self.assertEqual(response["error"], "Invalid tutor invocation payload.")
        self.assertTrue(
            any("Extra inputs are not permitted" in detail for detail in response["details"])
        )

    def test_input_guardrail_intervention_skips_workflow(self):
        with (
            patch(
                "jee_tutor.invocation.service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(
                    input_result=GuardrailCheck(
                        allowed=False,
                        message="Input blocked.",
                        action_reason="Denied topic",
                    )
                ),
            ),
            patch("jee_tutor.invocation.service.run_tutor_workflow") as run_tutor_workflow,
        ):
            response = handle_tutor_invocation(
                {
                    "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                    "task": "blocked context",
                }
            )

        self.assertEqual(
            response,
            {
                "error": "Input blocked.",
                "details": ["Denied topic"],
            },
        )
        run_tutor_workflow.assert_not_called()

    def test_legacy_media_payload_is_rejected(self):
        with self.assertLogs("jee_tutor.invocation.service", level="INFO") as logs:
            response = handle_tutor_invocation(
                {
                    "media": {
                        "type": "text",
                        "format": "plain",
                        "data": "ZmFrZQ==",
                    },
                    "prompt": "student context",
                }
            )

        self.assertEqual(response["error"], "Invalid tutor invocation payload.")
        self.assertTrue(response["details"])
        self.assertTrue(
            any(
                "agent_invocation metric_name=agent.invocations metric_value=1" in line
                for line in logs.output
            )
        )

    def test_output_guardrail_intervention_replaces_analysis(self):
        with (
            patch(
                "jee_tutor.invocation.service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(
                    output_result=GuardrailCheck(
                        allowed=False,
                        message="Sanitized guardrail response.",
                    )
                ),
            ),
            patch(
                "jee_tutor.invocation.service.run_tutor_workflow",
                return_value="raw unsafe analysis",
            ),
        ):
            response = handle_tutor_invocation(
                {
                    "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                }
            )

        self.assertEqual(response, {"analysis": "Sanitized guardrail response."})

    def test_successful_s3_invocation_returns_pdf_uri(self):
        from jee_tutor.artifacts.writer import AnalysisArtifactResult

        artifact_writer = FakeArtifactWriter(
            AnalysisArtifactResult(pdf_uri="s3://attempt-bucket/maths/analysis.pdf")
        )
        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **_: "analysis markdown",
            artifact_writer=artifact_writer,
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
            }
        )

        self.assertEqual(
            response,
            {
                "analysis": "analysis markdown",
                "message": (
                    "Your analysis PDF will be available at "
                    "s3://attempt-bucket/maths/analysis.pdf. "
                    "Please wait 5 minutes before opening it."
                ),
                "pdf_wait_minutes": 5,
                "analysis_pdf_uri": "s3://attempt-bucket/maths/analysis.pdf",
            },
        )
        self.assertEqual(artifact_writer.calls[0]["analysis_markdown"], "analysis markdown")

    def test_recipient_email_triggers_async_email_request(self):
        from jee_tutor.artifacts.writer import AnalysisArtifactResult

        image_resolver = Mock()
        image_resolver.resolve_images.return_value = [resolved_image()]
        email_coordinator = Mock()
        email_coordinator.request_delivery.return_value = EmailDeliveryOutcome(
            status=EmailDeliveryStatus.QUEUED,
            delivery_id="delivery-123",
        )
        artifact_writer = FakeArtifactWriter(
            AnalysisArtifactResult(pdf_uri="s3://attempt-bucket/maths/analysis.pdf")
        )
        service = TutorInvocationService(
            image_resolver=image_resolver,
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **_: "analysis markdown",
            artifact_writer=artifact_writer,
            email_coordinator=email_coordinator,
        )

        response = service.handle(
            {
                "image_s3_prefix": "s3://attempt-bucket/maths/attempt-123/",
                "recipient_email": "student@example.com",
                "save_analysis_pdf": False,
            }
        )

        self.assertEqual(response["analysis"], "analysis markdown")
        self.assertEqual(response["email_status"], "queued")
        self.assertEqual(response["email_delivery_id"], "delivery-123")
        self.assertEqual(response["analysis_pdf_uri"], "s3://attempt-bucket/maths/analysis.pdf")
        email_coordinator.request_delivery.assert_called_once()
        self.assertEqual(artifact_writer.calls[0]["analysis_markdown"], "analysis markdown")

    def test_pdf_artifact_failure_is_returned_without_dropping_analysis(self):
        from jee_tutor.artifacts.writer import AnalysisArtifactResult

        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **_: "analysis markdown",
            artifact_writer=FakeArtifactWriter(
                AnalysisArtifactResult(
                    markdown_uri="s3://attempt-bucket/maths/analysis.md",
                    errors=["Failed to write analysis PDF: RuntimeError: no tex"],
                )
            ),
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
            }
        )

        self.assertEqual(response["analysis"], "analysis markdown")
        self.assertEqual(response["analysis_markdown_uri"], "s3://attempt-bucket/maths/analysis.md")
        self.assertEqual(
            response["artifact_errors"],
            ["Failed to write analysis PDF: RuntimeError: no tex"],
        )

    def test_pdf_and_markdown_artifact_failures_keep_analysis(self):
        from jee_tutor.artifacts.writer import AnalysisArtifactResult

        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **_: "analysis markdown",
            artifact_writer=FakeArtifactWriter(
                AnalysisArtifactResult(
                    errors=[
                        "Failed to write analysis PDF: RuntimeError: no tex",
                        "Failed to write analysis markdown fallback: RuntimeError: s3 denied",
                    ],
                )
            ),
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
            }
        )

        self.assertEqual(response["analysis"], "analysis markdown")
        self.assertNotIn("analysis_pdf_uri", response)
        self.assertNotIn("analysis_markdown_uri", response)
        self.assertEqual(
            response["artifact_errors"],
            [
                "Failed to write analysis PDF: RuntimeError: no tex",
                "Failed to write analysis markdown fallback: RuntimeError: s3 denied",
            ],
        )

    def test_pdf_artifact_can_be_disabled_per_invocation(self):
        from jee_tutor.artifacts.writer import AnalysisArtifactResult

        artifact_writer = FakeArtifactWriter(
            AnalysisArtifactResult(pdf_uri="s3://attempt-bucket/maths/analysis.pdf")
        )
        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **_: "analysis markdown",
            artifact_writer=artifact_writer,
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                "save_analysis_pdf": False,
            }
        )

        self.assertEqual(response, {"analysis": "analysis markdown"})
        self.assertEqual(artifact_writer.calls, [])

    def test_workflow_failure_returns_descriptive_error_response(self):
        with self.assertLogs("jee_tutor.invocation.service", level="ERROR") as logs:
            with (
                patch(
                    "jee_tutor.invocation.service.RuntimeGuardrail",
                    return_value=FakeRuntimeGuardrail(),
                ),
                patch(
                    "jee_tutor.invocation.service.run_tutor_workflow",
                    side_effect=RuntimeError("Vision analyzer failed after resolving 1 image(s)."),
                ),
            ):
                response = handle_tutor_invocation(
                    {
                        "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                        "task": "diagnose failed attempt",
                    }
                )

        self.assertEqual(response["error"], "Tutor workflow failed while analyzing images.")
        self.assertTrue(any("tutor_workflow_error image_count=1" in line for line in logs.output))
        self.assertIn("Resolved image count: 1.", response["details"])
        self.assertIn("Question context provided: True.", response["details"])
        self.assertIn("Exception type: RuntimeError.", response["details"])
        self.assertIn(
            "Exception message: Vision analyzer failed after resolving 1 image(s).",
            response["details"],
        )

    def test_image_resolution_failure_returns_json_error(self):
        image_resolver = Mock()
        image_resolver.resolve_images.side_effect = RuntimeError("s3 access denied")
        workflow = Mock()
        service = TutorInvocationService(
            image_resolver=image_resolver,
            guardrail=FakeRuntimeGuardrail(),
            workflow=workflow,
            artifact_writer=FakeArtifactWriter(),
        )

        with self.assertLogs("jee_tutor.invocation.service", level="ERROR") as logs:
            response = service.handle(
                {
                    "image_s3_prefix": "s3://attempt-bucket/maths/",
                    "task": "diagnose maths attempt",
                }
            )

        self.assertEqual(response["error"], "Tutor invocation failed while resolving image inputs.")
        self.assertIn("Image sources provided: image_s3_prefix.", response["details"])
        self.assertIn("Exception type: RuntimeError.", response["details"])
        self.assertIn("Exception message: s3 access denied", response["details"])
        self.assertTrue(any("tutor_image_resolution_error" in line for line in logs.output))
        workflow.assert_not_called()

    def test_s3_prefix_images_are_sent_to_workflow_with_question_metadata(self):
        fake_s3_client = Mock()
        fake_s3_client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "maths/Question_19.png"}]}
        ]
        fake_s3_client.get_object.return_value = {
            "Body": Mock(read=Mock(return_value=b"s3-image-bytes"))
        }

        with (
            patch(
                "jee_tutor.invocation.service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(),
            ),
            patch.dict("os.environ", {"GOOGLE_API_KEY": "google-key"}),
            patch("jee_tutor.invocation.image_inputs.boto3.client", return_value=fake_s3_client),
            patch("jee_tutor.artifacts.writer.boto3.client", return_value=fake_s3_client),
            patch(
                "jee_tutor.artifacts.writer.PandocPdfRenderer",
                return_value=Mock(render=Mock(return_value=b"%PDF fake report")),
            ),
            patch(
                "jee_tutor.invocation.service.run_tutor_workflow",
                return_value="| Question Number | Chapter | Topic | What You Thought | "
                "Why That Thought Is Wrong | Exact Concept Gap | What You Must Deep-Dive |\n"
                "| --- | --- | --- | --- | --- | --- | --- |\n"
                "| 19 | Current Electricity | Resistance | Thought | Wrong | Gap | Study |",
            ) as run_tutor_workflow,
        ):
            response = handle_tutor_invocation(
                {
                    "image_s3_prefix": "s3://attempt-bucket/maths/",
                    "task": "diagnose maths attempt",
                    "subject": "Maths",
                }
            )

        self.assertEqual(
            response,
            {
                "analysis": (
                    "| Question Number | Chapter | Topic | What You Thought | "
                    "Why That Thought Is Wrong | Exact Concept Gap | What You Must Deep-Dive |\n"
                    "| --- | --- | --- | --- | --- | --- | --- |\n"
                    "| 19 | Current Electricity | Resistance | Thought | Wrong | Gap | Study |"
                ),
                "message": (
                    "Your analysis PDF will be available at "
                    "s3://attempt-bucket/maths/Maths_analysis.pdf. "
                    "Please wait 5 minutes before opening it."
                ),
                "pdf_wait_minutes": 5,
                "analysis_pdf_uri": "s3://attempt-bucket/maths/Maths_analysis.pdf",
            },
        )
        run_tutor_workflow.assert_called_once()
        self.assertEqual(run_tutor_workflow.call_args.kwargs["expected_question_numbers"], ["19"])
        image_url = run_tutor_workflow.call_args.kwargs["image_data_uris"][0]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))
        _, put_kwargs = fake_s3_client.put_object.call_args
        self.assertEqual(put_kwargs["Bucket"], "attempt-bucket")
        self.assertEqual(put_kwargs["Key"], "maths/Maths_analysis.pdf")
        self.assertTrue(put_kwargs["Body"].startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
