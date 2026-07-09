import ast
from pathlib import Path
import unittest

from jee_tutor.adapters.artifacts import AnalysisArtifactWriter
from jee_tutor.adapters.aws import ImageInputResolver
from jee_tutor.adapters.bedrock import RuntimeGuardrail
from jee_tutor.adapters.crewai import VisionAnalysisTool
from jee_tutor.adapters.email import EmailDeliveryCoordinator
from jee_tutor.adapters.langfuse import LangfuseObservability
from jee_tutor.adapters.litellm import VisionLLMClient


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src" / "jee_tutor"
FORBIDDEN_DOMAIN_IMPORT_PREFIXES = (
    "boto3",
    "crewai",
    "litellm",
    "langfuse",
    "bedrock_agentcore",
    "jee_tutor.adapters",
    "jee_tutor.agent.crew",
    "jee_tutor.agent.llm_client",
    "jee_tutor.agent.observability",
    "jee_tutor.agent.tools",
    "jee_tutor.email.ses_adapter",
)
FORBIDDEN_APPLICATION_IMPORT_PREFIXES = (
    "boto3",
    "crewai",
    "litellm",
    "langfuse",
    "bedrock_agentcore",
    "jee_tutor.email.ses_adapter",
)


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _assert_no_forbidden_imports(
    testcase: unittest.TestCase,
    package: str,
    forbidden_prefixes: tuple[str, ...],
) -> None:
    package_root = SRC_ROOT / package
    violations: list[str] = []
    for path in package_root.rglob("*.py"):
        for module_name in _imports_for(path):
            if module_name.startswith(forbidden_prefixes):
                relative = path.relative_to(PROJECT_ROOT)
                violations.append(f"{relative}: {module_name}")

    testcase.assertEqual(violations, [], "Forbidden imports found:\n" + "\n".join(violations))


class RuntimeBoundaryTest(unittest.TestCase):
    def test_domain_modules_do_not_import_concrete_adapters(self):
        _assert_no_forbidden_imports(self, "domain", FORBIDDEN_DOMAIN_IMPORT_PREFIXES)

    def test_application_modules_do_not_import_vendor_clients_directly(self):
        _assert_no_forbidden_imports(self, "application", FORBIDDEN_APPLICATION_IMPORT_PREFIXES)

    def test_adapter_exports_satisfy_runtime_ports(self):
        self.assertTrue(hasattr(ImageInputResolver, "resolve_images"))
        self.assertTrue(hasattr(RuntimeGuardrail, "check_input"))
        self.assertTrue(hasattr(RuntimeGuardrail, "check_output"))
        self.assertTrue(hasattr(LangfuseObservability, "invocation_span"))
        self.assertTrue(hasattr(VisionLLMClient, "analyze_vision"))
        self.assertTrue(hasattr(AnalysisArtifactWriter, "write_for_invocation"))
        self.assertTrue(hasattr(EmailDeliveryCoordinator, "request_delivery"))
        self.assertTrue(issubclass(VisionAnalysisTool, object))


if __name__ == "__main__":
    unittest.main()
