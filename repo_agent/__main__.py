from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .agent import RepoAnalysisAgent
from .github_tool import FailureInjector, GitHubTool
from .llm import OptionalLLMSummarizer
from .logger import setup_logger
from .models import AgentInputError, ToolError
from .reporting import render_markdown, result_to_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze a GitHub repository with a small agentic workflow.")
    parser.add_argument("goal", nargs="+", help="Natural-language goal. Include a GitHub repo URL or pass --repo-url.")
    parser.add_argument("--repo-url", help="GitHub repository URL if it is not included in the goal.")
    parser.add_argument("--max-files", type=int, default=10, help="Maximum number of source files to inspect.")
    parser.add_argument("--output", default="reports/report.md", help="Markdown report path.")
    parser.add_argument("--json-output", default="reports/report.json", help="JSON report path.")
    parser.add_argument("--demo-failure", action="store_true", help="Make the first GitHub API request fail once, then recover.")
    parser.add_argument("--no-llm", action="store_true", help="Skip optional Groq summary even if GROQ_API_KEY is set.")
    parser.add_argument("--log-file", type=Path, default=None, help="Write structured JSON logs to this file.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug-level logging on stderr.")
    parser.add_argument("--evaluate", action="store_true", help="Print agent quality metrics after the run.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logger("repo_agent", level=logging.DEBUG if args.verbose else logging.INFO, log_file=args.log_file)

    goal = " ".join(args.goal)
    github_tool = GitHubTool(failure_injector=FailureInjector(args.demo_failure))
    summarizer = None if args.no_llm else OptionalLLMSummarizer()
    agent = RepoAnalysisAgent(github_tool=github_tool, summarizer=summarizer, max_files=args.max_files)

    try:
        result = agent.run(goal, repo_url=args.repo_url)
    except AgentInputError as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        return 2
    except ToolError as exc:
        print(f"[fail] Tool execution stopped: {exc}", file=sys.stderr)
        return 1

    markdown = render_markdown(result)
    output_path = Path(args.output)
    json_path = Path(args.json_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(result_to_json(result), encoding="utf-8")

    print("")
    print("FINAL REPORT")
    print(markdown)
    print(f"[ok] Wrote Markdown report to {output_path}")
    print(f"[ok] Wrote JSON report to {json_path}")

    if args.evaluate:
        total = len(result.tool_events)
        ok = sum(1 for e in result.tool_events if e.status == "ok")
        fails = len(result.failures)
        recovered = sum(1 for f in result.failures if "retry" in f.recovery.lower() or "backoff" in f.recovery.lower())
        print(f"\n--- Agent Evaluation ---")
        print(f"Plan steps:         {len(result.plan)}")
        print(f"Tool calls made:    {total}")
        print(f"Successful:         {ok}")
        print(f"Failures:           {fails}")
        print(f"Recovered:          {recovered}")
        print(f"Findings produced:  {len(result.findings)}")
        print(f"Elapsed:            {result.metrics.get('elapsed_seconds', '?')}s")
        print(f"Success rate:       {ok / max(total, 1) * 100:.0f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
