import unittest
from unittest.mock import MagicMock

from repo_agent.agent import RepoAnalysisAgent
from repo_agent.github_tool import GitHubTool
from repo_agent.models import AgentInputError, RepoInfo, SourceFile, ToolError
from repo_agent.reporting import render_markdown, result_to_json


def _make_repo_info(owner="example", repo="project"):
    return RepoInfo(
        owner=owner, name=repo, full_name=f"{owner}/{repo}",
        html_url=f"https://github.com/{owner}/{repo}",
        description="A fake repository for tests.",
        default_branch="main", language="Python",
        stars=1, forks=0, open_issues=0,
        license_name="MIT", updated_at="2026-01-01T00:00:00Z",
    )


def _make_mock_github(*, fail_metadata_once=False):
    """Build a spec-bound mock so tests break if GitHubTool's interface changes."""
    mock = MagicMock(spec=GitHubTool)
    call_count = {"metadata": 0}

    def get_repo_info(owner, repo):
        call_count["metadata"] += 1
        if fail_metadata_once and call_count["metadata"] == 1:
            raise ToolError("temporary fake timeout", recoverable=True)
        return _make_repo_info(owner, repo)

    mock.get_repo_info.side_effect = get_repo_info
    mock.repo_exists.return_value = True
    mock.list_tree.return_value = [
        {"path": "app.py", "type": "blob", "size": 200},
        {"path": "tests/test_app.py", "type": "blob", "size": 100},
    ]
    content = "def run():\n    try:\n        return 1\n    except Exception:\n        return 0\n"
    mock.read_file.return_value = SourceFile("app.py", content, len(content), "Python")
    mock._call_count = call_count
    return mock


class AgentTests(unittest.TestCase):
    def test_agent_returns_structured_result(self):
        logs = []
        agent = RepoAnalysisAgent(github_tool=_make_mock_github(), stream=logs.append)
        result = agent.run("Analyze https://github.com/example/project for maintainability issues")
        self.assertEqual(result.repository.full_name, "example/project")
        self.assertEqual(result.execution_status, "completed")
        self.assertGreaterEqual(len(result.plan), 5)
        self.assertTrue(result.tools_used)
        self.assertTrue(any(f.title == "Broad exception handler" for f in result.findings))
        self.assertIn("PLAN", logs)
        self.assertIn("EXECUTION", logs)

    def test_plan_is_goal_dependent(self):
        mock = _make_mock_github()
        result_code = RepoAnalysisAgent(github_tool=mock, stream=None).run(
            "Analyze https://github.com/example/project for code quality")
        result_meta = RepoAnalysisAgent(github_tool=mock, stream=None).run(
            "Give me a stars and forks overview of https://github.com/example/project")
        # code goal should have more steps than metadata-only
        self.assertGreater(len(result_code.plan), len(result_meta.plan))

    def test_plan_includes_test_step_for_quality_goal(self):
        result = RepoAnalysisAgent(github_tool=_make_mock_github(), stream=None).run(
            "Analyze https://github.com/example/project for test coverage")
        step_titles = {s.title for s in result.plan}
        self.assertIn("Evaluate test presence and structure", step_titles)

    def test_recovery_after_failed_tool_call(self):
        logs = []
        mock = _make_mock_github(fail_metadata_once=True)
        agent = RepoAnalysisAgent(github_tool=mock, stream=logs.append)
        result = agent.run("Analyze https://github.com/example/project")
        self.assertEqual(result.execution_status, "completed")
        self.assertEqual(mock._call_count["metadata"], 2)
        self.assertTrue(result.failures)
        self.assertIn("recovered", result.recovery_summary)
        self.assertTrue(any("Retrying" in line for line in logs))

    def test_invalid_goal_is_reported(self):
        agent = RepoAnalysisAgent(github_tool=_make_mock_github(), stream=None)
        with self.assertRaises(AgentInputError):
            agent.run("Analyze this local folder instead")

    def test_nonexistent_repo_raises(self):
        mock = _make_mock_github()
        mock.repo_exists.return_value = False
        agent = RepoAnalysisAgent(github_tool=mock, stream=None)
        with self.assertRaises(AgentInputError) as ctx:
            agent.run("Analyze https://github.com/fake/nonexistent")
        self.assertIn("not found", str(ctx.exception))

    def test_result_can_be_serialized_to_json(self):
        result = RepoAnalysisAgent(github_tool=_make_mock_github(), stream=None).run(
            "Analyze https://github.com/example/project")
        payload = result_to_json(result)
        self.assertIn('"repository"', payload)
        self.assertIn('"tool_events"', payload)
        self.assertIn('"elapsed_seconds"', payload)

    def test_markdown_separates_evidence_from_possible_concerns(self):
        result = RepoAnalysisAgent(github_tool=_make_mock_github(), stream=None).run(
            "Analyze https://github.com/example/project")
        markdown = render_markdown(result)
        self.assertIn("## Evidence-Backed Findings", markdown)
        self.assertIn("## Possible Maintainability Concerns", markdown)
        self.assertIn("## Recovery Summary", markdown)

    def test_elapsed_time_is_recorded(self):
        result = RepoAnalysisAgent(github_tool=_make_mock_github(), stream=None).run(
            "Analyze https://github.com/example/project")
        self.assertIn("elapsed_seconds", result.metrics)
        self.assertGreaterEqual(result.metrics["elapsed_seconds"], 0)

    def test_all_retries_exhausted_raises(self):
        mock = _make_mock_github()
        mock.get_repo_info.side_effect = ToolError("server down", recoverable=True)
        agent = RepoAnalysisAgent(github_tool=mock, stream=None)
        with self.assertRaises(ToolError):
            agent.run("Analyze https://github.com/example/project")
        # should have tried 3 times before giving up
        self.assertEqual(mock.get_repo_info.call_count, 3)

    def test_llm_summarizer_failure_is_handled(self):
        mock = _make_mock_github()
        llm = MagicMock()
        llm.available = True
        llm.summarize.side_effect = ToolError("API down", recoverable=False)
        agent = RepoAnalysisAgent(github_tool=mock, summarizer=llm, stream=None)
        result = agent.run("Analyze https://github.com/example/project")
        # agent should complete even if LLM fails
        self.assertEqual(result.execution_status, "completed")
        self.assertIsNone(result.llm_summary)

    def test_llm_summarizer_called_with_findings(self):
        mock = _make_mock_github()
        llm = MagicMock()
        llm.available = True
        llm.summarize.return_value = "This repo has some issues."
        agent = RepoAnalysisAgent(github_tool=mock, summarizer=llm, stream=None)
        result = agent.run("Analyze https://github.com/example/project")
        llm.summarize.assert_called_once()
        self.assertEqual(result.llm_summary, "This repo has some issues.")


if __name__ == "__main__":
    unittest.main()
