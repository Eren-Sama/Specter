from __future__ import annotations

import json
from dataclasses import asdict

from .models import AgentResult, Finding

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def build_recommendations(findings: list[Finding]) -> list[str]:
    seen: set[str] = set()
    recommendations: list[str] = []
    for finding in sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.title)):
        if finding.recommendation not in seen:
            seen.add(finding.recommendation)
            recommendations.append(finding.recommendation)
        if len(recommendations) == 6:
            break
    if not recommendations:
        recommendations.append("No clear maintainability issues were found in the selected files; expand the scan before drawing a broad conclusion.")
    return recommendations


def result_to_json(result: AgentResult) -> str:
    return json.dumps(asdict(result), indent=2, ensure_ascii=True)


def render_markdown(result: AgentResult) -> str:
    repo = result.repository
    evidence_findings = [f for f in result.findings if f.confidence == "evidence"]
    possible_findings = [f for f in result.findings if f.confidence != "evidence"]

    lines = [
        "# GitHub Repository Analysis Report",
        "",
        "## Repository",
        "",
        f"- Name: {repo.full_name}",
        f"- URL: {repo.html_url}",
        f"- Description: {repo.description}",
        f"- Primary language: {repo.language}",
        f"- Default branch: {repo.default_branch}",
        f"- Stars: {repo.stars}",
        f"- Forks: {repo.forks}",
        f"- Open issues: {repo.open_issues}",
        f"- License: {repo.license_name}",
        "",
        "## User Goal",
        "",
        result.user_goal,
        "",
        "## Plan",
        "",
    ]
    for step in result.plan:
        lines.append(f"{step.number}. {step.title} - Tool: {step.tool}; expected: {step.expected_result}")

    lines.extend([
        "",
        "## Execution Status",
        "",
        result.execution_status,
        "",
        "## Recovery Summary",
        "",
        result.recovery_summary,
        "",
        "## Tools Used",
        "",
    ])
    for tool in result.tools_used:
        lines.append(f"- {tool}")

    lines.extend(["", "## Failures And Recovery", ""])
    if result.failures:
        for failure in result.failures:
            lines.append(f"- {failure.tool} while trying to {failure.action}: {failure.error}")
            lines.append(f"  Recovery: {failure.recovery}")
    else:
        lines.append("- No recoverable tool failures occurred during this run.")

    lines.extend(["", "## Evidence-Backed Findings", ""])
    _append_findings(lines, evidence_findings)

    lines.extend(["", "## Possible Maintainability Concerns", ""])
    _append_findings(lines, possible_findings)

    lines.extend(["## Recommendations", ""])
    for rec in result.recommendations:
        lines.append(f"- {rec}")

    lines.extend(["", "## Metrics", ""])
    for key, value in result.metrics.items():
        lines.append(f"- {key}: {value}")

    if result.llm_summary:
        lines.extend(["", "## Optional LLM Summary", "", result.llm_summary])

    lines.extend(["", "## Limitations", ""])
    for limitation in result.limitations:
        lines.append(f"- {limitation}")

    return "\n".join(lines).rstrip() + "\n"


def _append_findings(lines: list[str], findings: list[Finding]) -> None:
    if not findings:
        lines.append("No findings in this category.")
        return

    for i, finding in enumerate(findings, start=1):
        location = finding.path if finding.line is None else f"{finding.path}:{finding.line}"
        lines.extend([
            f"### {i}. [{finding.severity.upper()}] {finding.title}",
            "",
            f"- Location: {location}",
            f"- Confidence: {finding.confidence}",
            f"- Evidence: {finding.evidence}",
            f"- Recommendation: {finding.recommendation}",
            "",
        ])
