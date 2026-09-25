from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import PurePosixPath

from .github_tool import tree_has_license_file, tree_has_python_dependency_file, tree_has_readme, tree_has_tests
from .models import Finding, SourceFile

TODO_RE = re.compile(r"\b(TODO|FIXME)\b", re.IGNORECASE)
NESTING_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)


class StaticAnalyzer:
    def __init__(self, *, max_function_lines: int = 60, max_file_lines: int = 450, max_nesting: int = 5):
        self.max_function_lines = max_function_lines
        self.max_file_lines = max_file_lines
        self.max_nesting = max_nesting

    def analyze(self, files: list[SourceFile], *, tree: list[dict] | None = None) -> tuple[list[Finding], dict]:
        findings: list[Finding] = []
        languages = Counter(file.language for file in files)
        metrics = {
            "files_analyzed": len(files),
            "total_lines_analyzed": 0,
            "languages": dict(languages),
            "has_tests": tree_has_tests(tree or []),
            "has_readme": tree_has_readme(tree or []),
            "has_license_file": tree_has_license_file(tree or []),
            "has_python_dependency_file": tree_has_python_dependency_file(tree or []),
        }

        for file in files:
            lines = file.content.splitlines()
            metrics["total_lines_analyzed"] += len(lines)
            findings.extend(self._common_text_checks(file, lines))
            if PurePosixPath(file.path).suffix.lower() == ".py":
                findings.extend(self._python_checks(file, lines))

        if tree is not None:
            findings.extend(self._repository_checks(tree, metrics))

        return findings, metrics

    def _repository_checks(self, tree: list[dict], metrics: dict) -> list[Finding]:
        findings: list[Finding] = []
        paths = [str(item.get("path") or "") for item in tree]
        top_level_files = [path for path in paths if "/" not in path]

        if not metrics["has_tests"]:
            findings.append(Finding(
                title="No obvious test directory or test files found",
                severity="medium", path="repository tree", line=None,
                evidence="The repository tree did not include paths like tests/, test_*.py, or files under a test folder.",
                recommendation="Add a small automated test suite around core behavior before making larger changes.",
            ))

        if not metrics["has_readme"]:
            findings.append(Finding(
                title="README file was not found",
                severity="medium", path="repository tree", line=None,
                evidence="No top-level README file was visible in the repository tree.",
                recommendation="Add a README with setup, run instructions, examples, and project limitations.",
            ))

        if not metrics["has_license_file"]:
            findings.append(Finding(
                title="License file was not found",
                severity="low", path="repository tree", line=None,
                evidence="No top-level license file was visible in the repository tree.",
                recommendation="Add a LICENSE file if the project is intended to be reused or shared publicly.",
            ))

        has_python = any(str(item.get("path") or "").lower().endswith(".py") for item in tree)
        if has_python and not metrics["has_python_dependency_file"]:
            findings.append(Finding(
                title="Python dependency file was not found",
                severity="medium", path="repository tree", line=None,
                evidence="Python files were present, but no requirements.txt, pyproject.toml, setup.py, Pipfile, or environment.yml was found.",
                recommendation="Add a dependency file so another developer can recreate the Python environment.",
            ))

        if len(top_level_files) > 25:
            findings.append(Finding(
                title="Many top-level files",
                severity="low", path="repository tree", line=None,
                evidence=f"The repository has {len(top_level_files)} files at the root level.",
                recommendation="Group related files into folders if the root directory is becoming hard to scan.",
            ))

        return findings

    def _common_text_checks(self, file: SourceFile, lines: list[str]) -> list[Finding]:
        findings: list[Finding] = []
        if len(lines) > self.max_file_lines:
            findings.append(Finding(
                title="Large source file",
                severity="low", path=file.path, line=None,
                evidence=f"{file.path} has {len(lines)} lines.",
                recommendation="Review whether the file can be split around clearer responsibilities.",
            ))

        for number, line in enumerate(lines, start=1):
            if TODO_RE.search(line):
                findings.append(Finding(
                    title="TODO/FIXME marker left in source",
                    severity="low", path=file.path, line=number,
                    evidence=line.strip()[:180],
                    recommendation="Decide whether this marker should become an issue, be fixed now, or be removed.",
                    confidence="evidence",
                ))
        return findings

    def _python_checks(self, file: SourceFile, lines: list[str]) -> list[Finding]:
        try:
            tree = ast.parse(file.content)
        except SyntaxError as exc:
            return [Finding(
                title="Python syntax error",
                severity="high", path=file.path, line=exc.lineno,
                evidence=f"{exc.msg} at line {exc.lineno}.",
                recommendation="Fix the syntax error before relying on automated analysis or runtime behavior.",
                confidence="evidence",
            )]
        except Exception as exc:
            # guard against weird files that crash the parser
            return [Finding(
                title="Python parse failure",
                severity="medium", path=file.path, line=None,
                evidence=f"ast.parse raised {type(exc).__name__}: {exc}",
                recommendation="Inspect the file manually; the parser could not process it.",
                confidence="evidence",
            )]

        findings: list[Finding] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                findings.extend(self._function_checks(file, node))
            elif isinstance(node, ast.ExceptHandler) and self._is_broad_exception(node):
                findings.append(Finding(
                    title="Broad exception handler",
                    severity="medium", path=file.path, line=node.lineno,
                    evidence="The code catches a bare exception or the base Exception type.",
                    recommendation="Catch a more specific exception so real defects are not hidden.",
                    confidence="evidence",
                ))
        return findings

    def _function_checks(self, file: SourceFile, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[Finding]:
        findings: list[Finding] = []
        end_line = getattr(node, "end_lineno", None) or node.lineno
        length = end_line - node.lineno + 1

        if length > self.max_function_lines:
            findings.append(Finding(
                title="Long function",
                severity="medium", path=file.path, line=node.lineno,
                evidence=f"{node.name} is {length} lines long.",
                recommendation="Look for a natural helper function or smaller responsibility inside this function.",
            ))

        args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        if len(args) > 7:
            findings.append(Finding(
                title="Function has many parameters",
                severity="low", path=file.path, line=node.lineno,
                evidence=f"{node.name} has {len(args)} parameters.",
                recommendation="Consider grouping related values into a small data object if those parameters travel together.",
            ))

        nesting = self._max_nesting(node)
        if nesting >= self.max_nesting:
            findings.append(Finding(
                title="Deeply nested control flow",
                severity="medium", path=file.path, line=node.lineno,
                evidence=f"{node.name} reaches nesting depth {nesting}.",
                recommendation="Use early returns or extract part of the decision tree into a helper.",
            ))
        return findings

    def _max_nesting(self, node: ast.AST) -> int:
        def walk(current: ast.AST, depth: int) -> int:
            next_depth = depth + 1 if isinstance(current, NESTING_NODES) else depth
            best = next_depth
            for child in ast.iter_child_nodes(current):
                best = max(best, walk(child, next_depth))
            return best
        return walk(node, 0)

    def _is_broad_exception(self, node: ast.ExceptHandler) -> bool:
        if node.type is None:
            return True
        if isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}:
            return True
        return False
