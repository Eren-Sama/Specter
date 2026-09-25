from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ToolError(Exception):
    def __init__(self, message: str, *, recoverable: bool = False):
        super().__init__(message)
        self.recoverable = recoverable


class AgentInputError(ValueError):
    pass


@dataclass
class PlanStep:
    number: int
    title: str
    tool: str
    expected_result: str


@dataclass
class ToolEvent:
    tool: str
    action: str
    status: str
    detail: str
    elapsed_seconds: float = 0.0


@dataclass
class FailureEvent:
    tool: str
    action: str
    error: str
    recoverable: bool
    recovery: str


@dataclass
class RepoInfo:
    owner: str
    name: str
    full_name: str
    html_url: str
    description: str
    default_branch: str
    language: str
    stars: int
    forks: int
    open_issues: int
    license_name: str
    updated_at: str


@dataclass
class SourceFile:
    path: str
    content: str
    size: int
    language: str


@dataclass
class Finding:
    title: str
    severity: str
    path: str
    line: int | None
    evidence: str
    recommendation: str
    confidence: str = "potential"


@dataclass
class AgentResult:
    repository: RepoInfo
    user_goal: str
    plan: list[PlanStep]
    execution_status: str
    recovery_summary: str
    tools_used: list[str]
    tool_events: list[ToolEvent]
    failures: list[FailureEvent]
    findings: list[Finding]
    recommendations: list[str]
    limitations: list[str]
    metrics: dict[str, Any] = field(default_factory=dict)
    llm_summary: str | None = None

