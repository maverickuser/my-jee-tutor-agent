import unittest
from unittest.mock import Mock, patch

from jee_tutor.invocation.models import (
    AgentInvocationStatus,
    AgentLLMCallRecord,
    AgentLLMCallStatus,
)
from jee_tutor.invocation.status_store import (
    DynamoDbInvocationStatusStore,
    build_agent_invocation_record,
)


class FakeTable:
    def __init__(self):
        self.calls = []

    def update_item(self, **kwargs):
        self.calls.append(kwargs)
        return {}


class StatusStoreTest(unittest.TestCase):
    def test_null_status_store_is_a_noop(self):
        from jee_tutor.invocation.status_store import NullInvocationStatusStore

        store = NullInvocationStatusStore()
        self.assertIsNone(store.upsert_invocation(Mock()))
        self.assertIsNone(store.update_invocation("inv-1"))
        self.assertIsNone(store.append_llm_call("inv-1", Mock()))

    def test_config_from_environment_defaults_and_disables_without_table(self):
        from jee_tutor.invocation.status_store import InvocationStatusConfig

        with patch.dict("os.environ", {}, clear=True):
            config = InvocationStatusConfig.from_environment()

        self.assertEqual(config.table_name, "")
        self.assertEqual(config.region, "ap-south-1")
        self.assertFalse(config.enabled)

        with patch.dict(
            "os.environ",
            {
                "INVOCATION_STATUS_ENABLED": "false",
                "INVOCATION_STATUS_TABLE_NAME": "invocations",
                "AWS_DEFAULT_REGION": "us-east-1",
            },
            clear=True,
        ):
            config = InvocationStatusConfig.from_environment()

        self.assertEqual(config.table_name, "invocations")
        self.assertEqual(config.region, "us-east-1")
        self.assertFalse(config.enabled)

    def test_from_environment_returns_null_when_disabled(self):
        from jee_tutor.invocation.status_store import (
            DynamoDbInvocationStatusStore,
            NullInvocationStatusStore,
        )

        with patch.dict(
            "os.environ",
            {"INVOCATION_STATUS_ENABLED": "false", "INVOCATION_STATUS_TABLE_NAME": "invocations"},
            clear=True,
        ):
            store = DynamoDbInvocationStatusStore.from_environment()

        self.assertIsInstance(store, NullInvocationStatusStore)

    def test_build_agent_invocation_record_populates_required_fields(self):
        record = build_agent_invocation_record(
            invocation_id="inv-1",
            idempotency_key="key-1",
            status=AgentInvocationStatus.IN_PROGRESS,
            image_count=3,
            subject="Maths",
        )
        self.assertEqual(record.invocation_id, "inv-1")
        self.assertEqual(record.idempotency_key, "key-1")
        self.assertEqual(record.status, AgentInvocationStatus.IN_PROGRESS)
        self.assertEqual(record.image_count, 3)
        self.assertEqual(record.subject, "Maths")

    def test_dynamodb_store_upserts_all_populated_fields(self):
        table = FakeTable()
        resource = Mock()
        resource.Table.return_value = table
        store = DynamoDbInvocationStatusStore(table_name="invocations", region="ap-south-1")
        record = build_agent_invocation_record(
            invocation_id="inv-1",
            idempotency_key="key-1",
            status=AgentInvocationStatus.SUCCEEDED,
            image_count=2,
            subject="Physics",
            recipient_email="student@example.com",
            status_reason="done",
            runtime_commit_sha="sha-1",
            analysis_pdf_uri="s3://bucket/file.pdf",
            email_delivery_id="delivery-1",
            email_status="queued",
            email_error=None,
            error_type="Boom",
            error_message="boom",
            completed_at="2026-07-05T00:00:00Z",
        )

        with patch("jee_tutor.invocation.status_store.boto3.resource", return_value=resource):
            store.upsert_invocation(record)

        self.assertEqual(len(table.calls), 1)
        call = table.calls[0]
        self.assertEqual(call["Key"], {"invocation_id": "inv-1"})
        self.assertIn("created_at = if_not_exists(created_at, :created_at)", call["UpdateExpression"])
        self.assertIn("#status = :status", call["UpdateExpression"])
        self.assertEqual(call["ExpressionAttributeNames"]["#status"], "status")
        self.assertEqual(call["ExpressionAttributeValues"][":status"], "SUCCEEDED")
        self.assertEqual(call["ExpressionAttributeValues"][":image_count"], 2)
        self.assertEqual(call["ExpressionAttributeValues"][":subject"], "Physics")
        self.assertEqual(call["ExpressionAttributeValues"][":recipient_email"], "student@example.com")
        self.assertEqual(call["ExpressionAttributeValues"][":completed_at"], "2026-07-05T00:00:00Z")

    def test_dynamodb_store_update_invocation_noops_without_fields(self):
        table = FakeTable()
        resource = Mock()
        resource.Table.return_value = table
        store = DynamoDbInvocationStatusStore(table_name="invocations", region="ap-south-1")

        with patch("jee_tutor.invocation.status_store.boto3.resource", return_value=resource):
            self.assertIsNone(store.update_invocation("inv-1"))
            store.update_invocation("inv-1", status_reason=None)

        self.assertEqual(table.calls, [])

    def test_dynamodb_store_update_invocation_updates_fields(self):
        table = FakeTable()
        resource = Mock()
        resource.Table.return_value = table
        store = DynamoDbInvocationStatusStore(table_name="invocations", region="ap-south-1")

        with patch("jee_tutor.invocation.status_store.boto3.resource", return_value=resource):
            store.update_invocation("inv-1", status="SUCCEEDED", completed_at="2026-07-05T00:00:00Z")

        self.assertEqual(len(table.calls), 1)
        call = table.calls[0]
        self.assertEqual(call["Key"], {"invocation_id": "inv-1"})
        self.assertIn("#updated_at = :updated_at", call["UpdateExpression"])
        self.assertIn("#status = :status", call["UpdateExpression"])
        self.assertIn("#completed_at = :completed_at", call["UpdateExpression"])
        self.assertEqual(call["ExpressionAttributeNames"]["#status"], "status")
        self.assertEqual(call["ExpressionAttributeValues"][":status"], "SUCCEEDED")
        self.assertEqual(call["ExpressionAttributeValues"][":completed_at"], "2026-07-05T00:00:00Z")

    def test_dynamodb_store_appends_llm_call(self):
        table = FakeTable()
        resource = Mock()
        resource.Table.return_value = table
        store = DynamoDbInvocationStatusStore(table_name="invocations", region="ap-south-1")
        with patch("jee_tutor.invocation.status_store.boto3.resource", return_value=resource):
            store.append_llm_call(
                "inv-1",
                AgentLLMCallRecord(
                    llm_call_id="call-1",
                    batch_index=0,
                    batch_size=3,
                    model="gemini/gemini-2.5-pro",
                    provider="gemini",
                    purpose="vision_analysis",
                    status=AgentLLMCallStatus.SUCCEEDED,
                    attempt_number=1,
                    started_at="2026-07-05T00:00:00Z",
                    ended_at="2026-07-05T00:00:01Z",
                    duration_ms=1000,
                ),
            )
        self.assertEqual(len(table.calls), 1)
        self.assertIn("llm_calls = list_append", table.calls[0]["UpdateExpression"])


if __name__ == "__main__":
    unittest.main()
