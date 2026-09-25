from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .models import Finding, RepoInfo, ToolError


class OptionalLLMSummarizer:
    """Uses Groq to summarize findings when GROQ_API_KEY is set. Purely optional."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None, timeout: int = 25):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def summarize(self, goal: str, repo: RepoInfo, findings: list[Finding]) -> str | None:
        if not self.available:
            return None

        # cap at 12 findings to keep the prompt within token limits
        compact_findings = [
            {"title": f.title, "severity": f.severity, "path": f.path, "line": f.line, "evidence": f.evidence}
            for f in findings[:12]
        ]
        prompt = (
            "Write a concise repository analysis summary for a student assignment. "
            "Use only the facts below. Do not invent repository details or defects.\n\n"
            f"Goal: {goal}\n"
            f"Repository: {repo.full_name}\n"
            f"Description: {repo.description}\n"
            f"Findings JSON: {json.dumps(compact_findings, ensure_ascii=True)}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You summarize evidence from software-analysis tools clearly and honestly."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        request = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ToolError(f"LLM summary failed: {exc}", recoverable=False) from exc

        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ToolError("LLM response did not contain a usable summary.", recoverable=False) from exc
