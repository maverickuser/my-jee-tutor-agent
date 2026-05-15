import unittest
from pathlib import Path


class DockerfileTest(unittest.TestCase):
    def test_pdf_runtime_dependencies_include_lmodern_fonts(self):
        dockerfile = Path("src/Dockerfile").read_text(encoding="utf-8")

        self.assertIn("pandoc", dockerfile)
        self.assertIn("texlive-xetex", dockerfile)
        self.assertIn("texlive-science", dockerfile)
        self.assertIn("lmodern", dockerfile)


if __name__ == "__main__":
    unittest.main()
