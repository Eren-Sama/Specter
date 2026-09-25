import unittest
from pathlib import Path

from repo_agent.analysis_tool import StaticAnalyzer
from repo_agent.models import SourceFile


class StaticAnalyzerTests(unittest.TestCase):
    def test_detects_broad_exception_todo_and_long_function(self):
        lines = [
            "def risky(value):",
            "    # TODO: tighten this later",
            "    try:",
            "        value = int(value)",
            "    except Exception:",
            "        value = 0",
        ]
        lines.extend("    value += 1" for _ in range(65))
        lines.append("    return value")
        content = "\n".join(lines)
        file = SourceFile("app.py", content, len(content), "Python")
        findings, metrics = StaticAnalyzer(max_function_lines=20).analyze([file], tree=[])
        titles = {f.title for f in findings}
        self.assertIn("Broad exception handler", titles)
        self.assertIn("TODO/FIXME marker left in source", titles)
        self.assertIn("Long function", titles)
        self.assertEqual(metrics["files_analyzed"], 1)

    def test_detects_syntax_error(self):
        file = SourceFile("broken.py", "def nope(:\n    pass\n", 20, "Python")
        findings, _ = StaticAnalyzer().analyze([file])
        self.assertEqual(findings[0].title, "Python syntax error")
        self.assertEqual(findings[0].severity, "high")

    def test_analyzes_local_fixture_repo(self):
        fixture_root = Path(__file__).parent / "fixtures" / "sample_repo"
        app_path = fixture_root / "app.py"
        content = app_path.read_text(encoding="utf-8")
        tree = [
            {"path": "app.py", "type": "blob", "size": len(content)},
            {"path": "README.md", "type": "blob", "size": 80},
        ]
        file = SourceFile("app.py", content, len(content), "Python")
        findings, metrics = StaticAnalyzer(max_function_lines=15).analyze([file], tree=tree)
        titles = {f.title for f in findings}
        self.assertIn("Broad exception handler", titles)
        self.assertIn("Python dependency file was not found", titles)
        self.assertTrue(metrics["has_readme"])
        self.assertFalse(metrics["has_python_dependency_file"])


if __name__ == "__main__":
    unittest.main()
