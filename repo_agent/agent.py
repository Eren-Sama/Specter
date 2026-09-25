from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

from .analysis_tool import StaticAnalyzer
from .github_tool import GitHubTool, choose_source_files, parse_github_url, tree_has_tests
from .llm import OptionalLLMSummarizer
from .models import (
    AgentInputError, AgentResult, FailureEvent, Finding,
    PlanStep, RepoInfo, SourceFile, ToolError, ToolEvent,
)
from .reporting import build_recommendations

logger = logging.getLogger("repo_agent.agent")
T = TypeVar("T")

# used by _build_plan to figure out what steps are actually needed
_CODE_KEYWORDS = {"code", "quality", "maintainability", "refactor", "bug",
                  "security", "complexity", "function", "class", "analyze",
                  "analysis", "review", "inspect", "audit"}
_DEPENDENCY_KEYWORDS = {"dependency", "dependencies", "supply chain", "ci", "pipeline", "devops"}
_TEST_KEYWORDS = {"test", "coverage"}
_METADATA_ONLY_KEYWORDS = {"stars", "forks", "popularity", "overview", "summary", "metadata"}


class RepoAnalysisAgent:
    def __init__(
        self,
        *,
        github_tool: GitHubTool | None = None,
        analyzer: StaticAnalyzer | None = None,
        summarizer: OptionalLLMSummarizer | None = None,
        max_files: int = 10,
        stream: Callable[[str], None] | None = print,
    ):
        self.github_tool = github_tool or GitHubTool()
        self.analyzer = analyzer or StaticAnalyzer()
        self.summarizer = summarizer
        self.max_files = max_files
        self.stream = stream
        self.tool_events: list[ToolEvent] = []
        self.failures: list[FailureEvent] = []

    def run(self, goal: str, repo_url: str | None = None) -> AgentResult:
        run_start = time.perf_counter()
        self.tool_events = []
        self.failures = []
        goal = goal.strip()
        if not goal:
            raise AgentInputError("Please provide a natural-language goal.")

        url_text = repo_url or goal
        try:
            owner, repo_name = parse_github_url(url_text)
        except ValueError as exc:
            raise AgentInputError(str(exc)) from exc

        plan = self._build_plan(goal)
        self._emit("USER GOAL")
        self._emit(goal)
        self._emit("")
        self._emit(f"[plan] Analyzed goal and generated {len(plan)} steps")
        step_titles = {s.title for s in plan}
        if "Read selected source files" not in step_titles:
            self._emit("[plan] Skipped code-level analysis — goal appears metadata-focused")
        if "Inspect dependency and CI configuration files" in step_titles:
            self._emit("[plan] Added dependency/CI inspection (goal mentions dependencies or CI)")
        if "Evaluate test presence and structure" in step_titles:
            self._emit("[plan] Added test-health evaluation (goal mentions tests or coverage)")
        self._emit("PLAN")
        for step in plan:
            self._emit(f"{step.number}. {step.title}")
        self._emit("")
        self._emit("EXECUTION")

        # check if repo actually exists before we start the whole pipeline
        if not self.github_tool.repo_exists(owner, repo_name):
            self._emit(f"[fail] Repository {owner}/{repo_name} returned 404")
            raise AgentInputError(
                f"Repository {owner}/{repo_name} was not found on GitHub. "
                "Check the URL for typos or ensure it is public."
            )

        repo = self._call_with_retry(
            "GitHub API", "fetch repository metadata",
            lambda: self.github_tool.get_repo_info(owner, repo_name),
            validator=lambda info: bool(info.default_branch and info.html_url),
            success_detail="Repository metadata collected",
        )

        tree = self._call_with_retry(
            "GitHub API", "fetch repository file tree",
            lambda: self.github_tool.list_tree(owner, repo_name, repo.default_branch),
            validator=lambda items: len(items) > 0,
            success_detail="Repository file tree collected",
        )

        selected_paths = choose_source_files(tree, self.max_files)
        self._emit(f"[ok] Selected {len(selected_paths)} source files for inspection")

        source_files: list[SourceFile] = []
        findings: list[Finding] = []
        metrics: dict = {}

        if "Read selected source files" in step_titles:
            source_files = self._read_selected_files(repo, selected_paths)

        if "Run deterministic static analysis" in step_titles:
            findings, metrics = self._call_with_retry(
                "Python static analyzer", "inspect selected source files",
                lambda: self.analyzer.analyze(source_files, tree=tree),
                validator=lambda r: isinstance(r[0], list) and isinstance(r[1], dict),
                success_detail="Static analysis completed",
            )
        else:
            metrics = {"files_analyzed": 0, "total_lines_analyzed": 0, "languages": {}}

        if "Evaluate test presence and structure" in step_titles:
            self._check_test_health(tree, metrics)

        if "Inspect dependency and CI configuration files" in step_titles:
            self._check_dependencies(tree, findings)

        valid_findings = self._validate_findings(findings)
        recommendations = build_recommendations(valid_findings)
        llm_summary = self._optional_llm_summary(goal, repo, valid_findings)

        tools_used = ["GitHub API tool for repository metadata, tree, and file contents"]
        if source_files:
            tools_used.append("Python static-analysis tool using text checks and AST inspection")
        if llm_summary:
            tools_used.append("Optional LLM summarizer for final wording")

        limitations = [
            f"The agent inspects at most {self.max_files} source files per run to stay small and rate-limit friendly.",
            "Static-analysis findings are maintainability signals, not guaranteed software defects.",
            "Private repositories or higher GitHub rate limits require setting GITHUB_TOKEN.",
        ]
        if not source_files:
            limitations.append("No source files were downloaded, so the report is based only on repository metadata and tree signals.")

        elapsed = time.perf_counter() - run_start
        result = AgentResult(
            repository=repo,
            user_goal=goal,
            plan=plan,
            execution_status="completed",
            recovery_summary=self._recovery_summary(),
            tools_used=tools_used,
            tool_events=self.tool_events,
            failures=self.failures,
            findings=valid_findings,
            recommendations=recommendations,
            limitations=limitations,
            metrics=metrics | {"selected_files": selected_paths, "elapsed_seconds": round(elapsed, 2)},
            llm_summary=llm_summary,
        )
        self._emit(f"[ok] Final structured report prepared in {elapsed:.1f}s")
        return result

    def _build_plan(self, goal: str) -> list[PlanStep]:
        """Build a plan based on what the goal actually asks for."""
        goal_lower = goal.lower()
        steps: list[PlanStep] = []
        n = 0

        n += 1
        steps.append(PlanStep(n, "Validate the GitHub repository URL and user goal", "URL parser", "owner and repo name"))
        n += 1
        steps.append(PlanStep(n, "Gather repository metadata", "GitHub API", "basic project context"))
        n += 1
        steps.append(PlanStep(n, "Inspect the repository file tree", "GitHub API", "candidate source files"))

        needs_code = any(kw in goal_lower for kw in _CODE_KEYWORDS)
        metadata_only = any(kw in goal_lower for kw in _METADATA_ONLY_KEYWORDS) and not needs_code

        if not metadata_only:
            n += 1
            steps.append(PlanStep(n, "Read selected source files", "GitHub contents API", "source text for analysis"))
            n += 1
            steps.append(PlanStep(n, "Run deterministic static analysis", "Python AST/text analyzer", "evidence-backed findings"))

        if any(kw in goal_lower for kw in _DEPENDENCY_KEYWORDS):
            n += 1
            steps.append(PlanStep(n, "Inspect dependency and CI configuration files", "GitHub contents API", "dependency health signals"))

        if any(kw in goal_lower for kw in _TEST_KEYWORDS):
            n += 1
            steps.append(PlanStep(n, "Evaluate test presence and structure", "repository tree inspector", "test health assessment"))

        n += 1
        steps.append(PlanStep(n, "Validate findings and prepare a structured report", "agent reviewer", "final Markdown/JSON result"))

        return steps

    def _recovery_summary(self) -> str:
        if not self.failures:
            return "No recoverable tool failure occurred during this run."

        recovered = []
        failed_pairs = {(f.tool, f.action) for f in self.failures}
        for tool, action in failed_pairs:
            if any(e.tool == tool and e.action == action and e.status == "ok" for e in self.tool_events):
                recovered.append(f"{tool} recovered while trying to {action}.")

        if recovered:
            return " ".join(recovered)
        return "A tool failure occurred and was recorded; unrecovered failures stop the run before a final report is written."

    def _read_selected_files(self, repo: RepoInfo, selected_paths: list[str]) -> list[SourceFile]:
        files: list[SourceFile] = []
        for path in selected_paths:
            try:
                file = self._call_with_retry(
                    "GitHub contents API", f"read {path}",
                    lambda path=path: self.github_tool.read_file(repo.owner, repo.name, path, repo.default_branch),
                    validator=lambda result: bool(result.content),
                    success_detail=f"Read {path}",
                )
            except ToolError as exc:
                self._emit(f"[warn] Skipping {path}: {exc}")
                continue
            files.append(file)
        return files

    def _check_test_health(self, tree: list[dict], metrics: dict) -> None:
        has_tests = tree_has_tests(tree)
        metrics["has_tests"] = has_tests
        test_paths = [str(item.get("path", "")) for item in tree if "test" in str(item.get("path", "")).lower()]
        self._emit(f"[ok] Test health: {'found ' + str(len(test_paths)) + ' test file(s)' if has_tests else 'no tests detected'}")
        self.tool_events.append(ToolEvent("repository tree inspector", "evaluate test health", "ok", f"has_tests={has_tests}", 0.0))

    def _check_dependencies(self, tree: list[dict], findings: list[Finding]) -> None:
        dep_names = {"requirements.txt", "pyproject.toml", "setup.py", "pipfile", "package.json"}
        ci_patterns = {".github/workflows", ".gitlab-ci.yml", "Jenkinsfile", ".circleci"}
        dep_files = [str(item.get("path", "")) for item in tree if str(item.get("path", "")).lower() in dep_names]
        ci_files = [str(item.get("path", "")) for item in tree
                    if any(p in str(item.get("path", "")).lower() for p in ci_patterns)]
        self._emit(f"[ok] Found {len(dep_files)} dependency file(s), {len(ci_files)} CI config(s)")
        if not ci_files:
            findings.append(Finding(
                title="No CI/CD configuration detected",
                severity="low", path="repository tree", line=None,
                evidence="No GitHub Actions, GitLab CI, Jenkins, or CircleCI configuration was found.",
                recommendation="Add a CI pipeline to run tests and linting automatically on each push.",
            ))
        self.tool_events.append(ToolEvent("GitHub contents API", "inspect dependency and CI files", "ok",
                                          f"deps={len(dep_files)}, ci={len(ci_files)}", 0.0))

    def _validate_findings(self, findings: list[Finding]) -> list[Finding]:
        valid = []
        dropped_details: list[str] = []
        for f in findings:
            if f.title and f.path and f.evidence and f.recommendation:
                valid.append(f)
            else:
                missing = [field for field, val in [("title", f.title), ("path", f.path),
                           ("evidence", f.evidence), ("recommendation", f.recommendation)] if not val]
                dropped_details.append(f"  dropped finding (missing {', '.join(missing)})")

        detail = f"Validated {len(valid)} findings"
        if dropped_details:
            detail += f"; dropped {len(dropped_details)} incomplete findings"
            for line in dropped_details:
                self._emit(line)
        self.tool_events.append(ToolEvent("agent reviewer", "validate static-analysis findings", "ok", detail, 0.0))
        self._emit(f"[ok] {detail}")

        return sorted(valid, key=lambda f: ({"high": 0, "medium": 1, "low": 2}.get(f.severity, 9), f.path, f.line or 0))

    def _optional_llm_summary(self, goal: str, repo: RepoInfo, findings: list[Finding]) -> str | None:
        if not self.summarizer or not self.summarizer.available:
            return None
        try:
            return self._call_with_retry(
                "LLM summarizer", "summarize evidence",
                lambda: self.summarizer.summarize(goal, repo, findings),
                validator=lambda text: bool(text),
                attempts=1,
                success_detail="LLM summary prepared",
            )
        except ToolError as exc:
            self._emit(f"[warn] Continuing without LLM summary: {exc}")
            return None

    def _call_with_retry(
        self,
        tool: str,
        action: str,
        call: Callable[[], T],
        *,
        validator: Callable[[T], bool] | None = None,
        attempts: int = 3,
        base_delay: float = 1.0,
        success_detail: str | None = None,
    ) -> T:
        for attempt in range(1, attempts + 1):
            self._emit(f"-> {tool}: {action} (attempt {attempt}/{attempts})")
            t0 = time.perf_counter()
            try:
                result = call()
                elapsed = time.perf_counter() - t0
                if validator and not validator(result):
                    raise ToolError("Tool result did not pass validation.", recoverable=True)
                detail = f"{success_detail or action} ({elapsed:.2f}s)"
                self.tool_events.append(ToolEvent(tool, action, "ok", detail, round(elapsed, 3)))
                self._emit(f"[ok] {detail}")
                return result
            except ToolError as exc:
                elapsed = time.perf_counter() - t0
                self.tool_events.append(ToolEvent(tool, action, "failed", str(exc), round(elapsed, 3)))
                can_retry = exc.recoverable and attempt < attempts
                if can_retry:
                    delay = base_delay * (2 ** (attempt - 1))
                    self.failures.append(FailureEvent(tool, action, str(exc), True,
                                                      f"Waiting {delay:.1f}s before retry (exponential backoff)."))
                    self._emit(f"[warn] {tool} failed: {exc}")
                    self._emit(f"-> Retrying in {delay:.1f}s after recoverable failure")
                    time.sleep(delay)
                    continue
                self.failures.append(FailureEvent(tool, action, str(exc), exc.recoverable,
                                                  "No retry was available; the step was reported to the caller."))
                raise

        raise ToolError(f"{tool} failed after {attempts} attempts: {action}.", recoverable=False)

    def _emit(self, message: str) -> None:
        if self.stream:
            self.stream(message)
        if "[fail]" in message or "[warn]" in message:
            logger.warning(message)
        elif "[ok]" in message:
            logger.info(message)
        else:
            logger.debug(message)
