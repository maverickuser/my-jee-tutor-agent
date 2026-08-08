import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ModelRoutingBoundaryTest(unittest.TestCase):
    def test_execution_profile_does_not_enter_domain_application_or_tool_policy(self):
        protected = [
            *sorted((ROOT / "src/jee_tutor/domain").glob("**/*.py")),
            *sorted((ROOT / "src/jee_tutor/application").glob("**/*.py")),
            ROOT / "src/jee_tutor/agent/tools.py",
            ROOT / "src/jee_tutor/agent/prompts.py",
        ]
        violations = []
        for path in protected:
            if not path.exists():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "jee_tutor.model_routing":
                    violations.append(str(path.relative_to(ROOT)))
                if isinstance(node, ast.Name) and node.id == "ExecutionProfile":
                    violations.append(str(path.relative_to(ROOT)))

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
