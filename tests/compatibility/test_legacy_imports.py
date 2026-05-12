import unittest


class LegacyImportTest(unittest.TestCase):
    def test_legacy_root_imports_reexport_new_package_objects(self):
        from agentcore_handler import handle_tutor_invocation as legacy_handler
        from analysis_artifacts import AnalysisArtifactWriter as LegacyArtifactWriter
        from analysis_pdf import PandocPdfRenderer as LegacyPdfRenderer
        from image_inputs import ImageInputResolver as LegacyImageInputResolver
        from invocation_models import TutorInvocationPayload as LegacyPayload
        from jee_tutor.artifacts.pdf import PandocPdfRenderer
        from jee_tutor.artifacts.writer import AnalysisArtifactWriter
        from jee_tutor.handler import handle_tutor_invocation
        from jee_tutor.invocation.image_inputs import ImageInputResolver
        from jee_tutor.invocation.models import TutorInvocationPayload
        from jee_tutor.invocation.service import TutorInvocationService
        from tutor_invocation_service import TutorInvocationService as LegacyService

        self.assertIs(legacy_handler, handle_tutor_invocation)
        self.assertIs(LegacyArtifactWriter, AnalysisArtifactWriter)
        self.assertIs(LegacyPdfRenderer, PandocPdfRenderer)
        self.assertIs(LegacyImageInputResolver, ImageInputResolver)
        self.assertIs(LegacyPayload, TutorInvocationPayload)
        self.assertIs(LegacyService, TutorInvocationService)

    def test_legacy_agent_package_reexports_new_agent_objects(self):
        from agents.tutor_agent import VisionLLMClient as LegacyVisionLLMClient
        from agents.tutor_agent.guardrails import RuntimeGuardrail as LegacyRuntimeGuardrail
        from jee_tutor.agent import VisionLLMClient
        from jee_tutor.agent.guardrails import RuntimeGuardrail

        self.assertIs(LegacyVisionLLMClient, VisionLLMClient)
        self.assertIs(LegacyRuntimeGuardrail, RuntimeGuardrail)


if __name__ == "__main__":
    unittest.main()
