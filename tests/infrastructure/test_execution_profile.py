import hashlib
import hmac
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.model_config import CrewAIModelConfig, VisionModelConfig
from jee_tutor.agent.observability import LangfuseObservability
from jee_tutor.handler import handle_agentcore_request
from jee_tutor.infrastructure.execution_profile import (
    CD_RUN_ID_HEADER,
    CD_SIGNATURE_HEADER,
    CD_TIMESTAMP_HEADER,
    EXECUTION_PROFILE_HEADER,
    CdExecutionProfileAuthenticator,
    CdExecutionRequestSigner,
    ExecutionProfileAuthorizationError,
    _load_cd_execution_secret,
    _parse_timestamp,
    attach_agentcore_cd_headers,
    build_cd_request_headers,
    canonical_payload_bytes,
    canonical_cd_signature_input,
    default_cd_authenticator,
    load_cd_execution_secret,
    resolve_execution_profile,
)
from jee_tutor.model_routing import (
    CD_EMBEDDING_MODEL,
    CD_GENERATION_MODEL,
    LIVE_EMBEDDING_MODEL,
    LIVE_GENERATION_MODEL,
    ExecutionProfile,
    active_model_bundle,
    is_gemini_36_model,
    resolve_model_bundle,
    use_model_bundle,
)
from jee_tutor.profile.embeddings import ProfileEmbeddingConfig
from jee_tutor.profile.model_config import ProfileClassifierModelConfig


PAYLOAD = {"task": "profile", "subject": "Physics"}
SECRET = "unit-test-secret"
NOW = 1_800_000_000


class ExecutionProfileAuthenticationTest(unittest.TestCase):
    def setUp(self):
        self.authenticator = CdExecutionProfileAuthenticator(
            secret_provider=lambda: SECRET,
            now=lambda: NOW,
        )

    def test_missing_headers_select_live(self):
        self.assertEqual(
            self.authenticator.resolve(payload=PAYLOAD, request_headers=None),
            ExecutionProfile.LIVE,
        )

    def test_valid_headers_select_cd_and_are_case_insensitive(self):
        headers = build_cd_request_headers(
            secret=SECRET,
            run_id="1234",
            payload=PAYLOAD,
            timestamp=NOW,
        )

        result = self.authenticator.resolve(
            payload=PAYLOAD,
            request_headers={name.lower(): value for name, value in headers.items()},
        )

        self.assertEqual(result, ExecutionProfile.CD)

    def test_signature_matches_documented_canonical_value(self):
        payload_hash = hashlib.sha256(canonical_payload_bytes(PAYLOAD)).hexdigest()
        canonical = canonical_cd_signature_input(
            timestamp=NOW,
            run_id="run-1",
            payload_hash=payload_hash,
        )
        expected = hmac.new(SECRET.encode(), canonical, hashlib.sha256).hexdigest()

        headers = build_cd_request_headers(
            secret=SECRET,
            run_id="run-1",
            payload=PAYLOAD,
            timestamp=NOW,
        )

        self.assertEqual(headers[CD_SIGNATURE_HEADER], expected)

    def test_partial_malformed_expired_invalid_and_tampered_headers_are_rejected(self):
        valid = build_cd_request_headers(
            secret=SECRET,
            run_id="run-1",
            payload=PAYLOAD,
            timestamp=NOW,
        )
        cases = [
            {EXECUTION_PROFILE_HEADER: "cd"},
            {**valid, CD_TIMESTAMP_HEADER: "not-a-time"},
            build_cd_request_headers(
                secret=SECRET,
                run_id="run-1",
                payload=PAYLOAD,
                timestamp=NOW - 301,
            ),
            {**valid, CD_SIGNATURE_HEADER: "0" * 64},
            {**valid, CD_RUN_ID_HEADER: ""},
        ]
        for headers in cases:
            with self.subTest(headers=headers):
                with self.assertRaises(ExecutionProfileAuthorizationError):
                    self.authenticator.resolve(
                        payload=PAYLOAD,
                        request_headers=headers,
                    )

        with self.assertRaises(ExecutionProfileAuthorizationError):
            self.authenticator.resolve(
                payload={**PAYLOAD, "subject": "Maths"},
                request_headers=valid,
            )

        with self.assertRaises(ExecutionProfileAuthorizationError):
            self.authenticator.resolve(
                payload=PAYLOAD,
                request_headers={**valid, EXECUTION_PROFILE_HEADER: "live"},
            )

    def test_signature_comparison_is_constant_time(self):
        headers = build_cd_request_headers(
            secret=SECRET,
            run_id="run-1",
            payload=PAYLOAD,
            timestamp=NOW,
        )
        with patch(
            "jee_tutor.infrastructure.execution_profile.hmac.compare_digest",
            wraps=hmac.compare_digest,
        ) as compare:
            self.authenticator.resolve(payload=PAYLOAD, request_headers=headers)
        compare.assert_called_once()

    def test_invalid_signature_stops_before_task_or_provider_composition(self):
        headers = build_cd_request_headers(
            secret="wrong-secret",
            run_id="run-1",
            payload=PAYLOAD,
            timestamp=NOW,
        )
        with patch("jee_tutor.handler.handle_agentcore_task") as task:
            response = handle_agentcore_request(
                PAYLOAD,
                request_headers=headers,
                authenticator=self.authenticator,
            )

        task.assert_not_called()
        self.assertEqual(response["error"], "Unauthorized execution profile.")

    def test_agentcore_handler_composes_cd_or_live_bundle_before_task_routing(self):
        headers = build_cd_request_headers(
            secret=SECRET,
            run_id="run-1",
            payload=PAYLOAD,
            timestamp=NOW,
        )

        def selected_models(_payload):
            bundle = active_model_bundle()
            return {
                "profile": bundle.execution_profile.value,
                "generation": bundle.generation_model,
                "embedding": bundle.embedding_model,
            }

        with patch("jee_tutor.handler.handle_agentcore_task", side_effect=selected_models):
            cd = handle_agentcore_request(
                PAYLOAD,
                request_headers=headers,
                authenticator=self.authenticator,
            )
            live = handle_agentcore_request(
                PAYLOAD,
                request_headers=None,
                authenticator=self.authenticator,
            )

        self.assertEqual(
            cd,
            {
                "profile": "cd",
                "generation": CD_GENERATION_MODEL,
                "embedding": CD_EMBEDDING_MODEL,
            },
        )
        self.assertEqual(
            live,
            {
                "profile": "live",
                "generation": LIVE_GENERATION_MODEL,
                "embedding": LIVE_EMBEDDING_MODEL,
            },
        )

    def test_request_signer_injects_headers_before_sigv4_and_unregisters(self):
        events = Mock()
        client = Mock()
        client.meta.events = events
        request = Mock()
        request.headers = {}
        signer = CdExecutionRequestSigner(
            secret=SECRET,
            run_id="run-1",
            now=lambda: NOW,
        )

        with attach_agentcore_cd_headers(client, signer.headers(PAYLOAD)):
            callback = events.register_first.call_args.args[1]
            callback(request)

        self.assertEqual(request.headers[EXECUTION_PROFILE_HEADER], "cd")
        self.assertEqual(request.headers[CD_TIMESTAMP_HEADER], str(NOW))
        events.unregister.assert_called_once()

    def test_header_attachment_unregisters_when_invocation_raises(self):
        client = Mock()
        with self.assertRaisesRegex(RuntimeError, "provider failed"):
            with attach_agentcore_cd_headers(client, {"header": "value"}):
                raise RuntimeError("provider failed")
        client.meta.events.unregister.assert_called_once()

    def test_default_header_timestamp_and_default_authenticator_path(self):
        with patch("jee_tutor.infrastructure.execution_profile.time.time", return_value=NOW):
            headers = build_cd_request_headers(
                secret=SECRET,
                run_id="run-1",
                payload=PAYLOAD,
            )
        self.assertEqual(headers[CD_TIMESTAMP_HEADER], str(NOW))
        self.assertEqual(
            resolve_execution_profile(payload=PAYLOAD, request_headers=None),
            ExecutionProfile.LIVE,
        )
        self.assertIs(default_cd_authenticator(), default_cd_authenticator())

    def test_secret_loading_success_and_safe_failures(self):
        client = Mock()
        client.get_secret_value.return_value = {"SecretString": SECRET}
        self.assertEqual(
            load_cd_execution_secret("arn:secret", secrets_client=client),
            SECRET,
        )
        client.get_secret_value.return_value = {"SecretString": ""}
        with self.assertRaisesRegex(
            ExecutionProfileAuthorizationError,
            "not configured",
        ):
            load_cd_execution_secret("arn:secret", secrets_client=client)
        client.get_secret_value.side_effect = RuntimeError("unavailable")
        with self.assertRaisesRegex(
            ExecutionProfileAuthorizationError,
            "unavailable",
        ):
            load_cd_execution_secret("arn:secret", secrets_client=client)

    def test_environment_secret_loader_requires_arn_and_delegates(self):
        _load_cd_execution_secret.cache_clear()
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(
                ExecutionProfileAuthorizationError,
                "not configured",
            ):
                _load_cd_execution_secret()

        _load_cd_execution_secret.cache_clear()
        with (
            patch.dict(
                "os.environ",
                {"CD_EXECUTION_HMAC_SECRET_ARN": "arn:secret"},
                clear=True,
            ),
            patch(
                "jee_tutor.infrastructure.execution_profile.load_cd_execution_secret",
                return_value=SECRET,
            ) as load,
        ):
            self.assertEqual(_load_cd_execution_secret(), SECRET)
        load.assert_called_once_with("arn:secret")
        _load_cd_execution_secret.cache_clear()

    def test_timestamp_parser_rejects_non_string_values(self):
        with self.assertRaises(ExecutionProfileAuthorizationError):
            _parse_timestamp(None)


class ModelResolutionTest(unittest.TestCase):
    def test_exact_default_matrix(self):
        cd = resolve_model_bundle(ExecutionProfile.CD, {})
        live = resolve_model_bundle(ExecutionProfile.LIVE, {})

        self.assertEqual((cd.generation_model, cd.embedding_model), (
            CD_GENERATION_MODEL,
            CD_EMBEDDING_MODEL,
        ))
        self.assertEqual((live.generation_model, live.embedding_model), (
            LIVE_GENERATION_MODEL,
            LIVE_EMBEDDING_MODEL,
        ))
        self.assertEqual(
            live.trace_metadata,
            {
                "execution_profile": "live",
                "generation_model": LIVE_GENERATION_MODEL,
                "embedding_model": LIVE_EMBEDDING_MODEL,
            },
        )

    def test_profile_specific_environment_overrides_and_model_detection(self):
        cd = resolve_model_bundle(
            ExecutionProfile.CD,
            {
                "CD_GENERATION_MODEL": "gemini/cd-generation",
                "CD_EMBEDDING_MODEL": "gemini/cd-embedding",
            },
        )
        live = resolve_model_bundle(
            ExecutionProfile.LIVE,
            {
                "LIVE_GENERATION_MODEL": "gemini/live-generation",
                "LIVE_EMBEDDING_MODEL": "gemini/live-embedding",
            },
        )
        self.assertEqual(cd.generation_model, "gemini/cd-generation")
        self.assertEqual(cd.embedding_model, "gemini/cd-embedding")
        self.assertEqual(live.generation_model, "gemini/live-generation")
        self.assertEqual(live.embedding_model, "gemini/live-embedding")
        self.assertTrue(is_gemini_36_model("google/gemini-3.6-flash"))
        self.assertFalse(is_gemini_36_model("gemini/gemini-2.5-flash-lite"))

    def test_profile_context_routes_every_model_configuration(self):
        config = LLMConfig({"completion": {"temperature": 0.2}})
        environ = {"GOOGLE_API_KEY": "key"}
        with use_model_bundle(resolve_model_bundle(ExecutionProfile.CD, {})):
            self.assertEqual(VisionModelConfig(environ, config).resolve().model, CD_GENERATION_MODEL)
            self.assertEqual(CrewAIModelConfig(environ, config).resolve().model, CD_GENERATION_MODEL)
            self.assertEqual(
                ProfileClassifierModelConfig(environ=environ, config=config).resolve().model,
                CD_GENERATION_MODEL,
            )
            self.assertEqual(
                ProfileEmbeddingConfig(environ=environ, config=config).resolve().model,
                CD_EMBEDDING_MODEL,
            )
            self.assertEqual(
                LangfuseObservability(config).default_metadata,
                {
                    "execution_profile": "cd",
                    "generation_model": CD_GENERATION_MODEL,
                    "embedding_model": CD_EMBEDDING_MODEL,
                },
            )

    def test_cd_and_live_contexts_do_not_leak_across_threads_or_mutate_environment(self):
        environ = {"UNCHANGED": "value", "GOOGLE_API_KEY": "key"}

        def resolve(profile):
            with use_model_bundle(resolve_model_bundle(profile, {})):
                bundle = active_model_bundle()
                return bundle.generation_model, bundle.embedding_model

        with ThreadPoolExecutor(max_workers=2) as executor:
            cd_future = executor.submit(resolve, ExecutionProfile.CD)
            live_future = executor.submit(resolve, ExecutionProfile.LIVE)

        self.assertEqual(cd_future.result(), (CD_GENERATION_MODEL, CD_EMBEDDING_MODEL))
        self.assertEqual(live_future.result(), (LIVE_GENERATION_MODEL, LIVE_EMBEDDING_MODEL))
        self.assertEqual(environ, {"UNCHANGED": "value", "GOOGLE_API_KEY": "key"})
        self.assertIsNone(active_model_bundle())


if __name__ == "__main__":
    unittest.main()
