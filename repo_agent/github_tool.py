from __future__ import annotations

import base64
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import PurePosixPath
from typing import Any

from .models import RepoInfo, SourceFile, ToolError

SOURCE_EXTENSIONS = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
}

MAX_SOURCE_BYTES = 120_000

SKIP_PARTS = {
    ".git", ".venv", "__pycache__", "build", "dist",
    "node_modules", "site-packages", "vendor",
}


def parse_github_url(text: str) -> tuple[str, str]:
    """Extract (owner, repo) from text containing a GitHub URL."""
    match = re.search(r"github\.com[:/](?P<owner>[^/\s:]+)/(?P<repo>[^/\s?#]+)", text)
    if not match:
        raise ValueError("No GitHub repository URL was found.")

    owner = match.group("owner").strip()
    repo = match.group("repo").strip().rstrip(".,)")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise ValueError("GitHub URL is missing an owner or repository name.")
    return owner, repo


class FailureInjector:
    """When enabled, makes the first should_fail() call return True to simulate a transient error."""

    def __init__(self, enabled: bool = False):
        self.remaining = {"github_api": 1} if enabled else {}

    def should_fail(self, key: str) -> bool:
        count = self.remaining.get(key, 0)
        if count <= 0:
            return False
        self.remaining[key] = count - 1
        return True


class GitHubTool:
    def __init__(
        self,
        *,
        token: str | None = None,
        api_base: str = "https://api.github.com",
        timeout: int = 20,
        failure_injector: FailureInjector | None = None,
    ):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.failure_injector = failure_injector or FailureInjector(False)
        self._cache: dict[str, dict[str, Any]] = {}

    def get_repo_info(self, owner: str, repo: str) -> RepoInfo:
        data = self._request_json(f"/repos/{owner}/{repo}")
        required = ["full_name", "html_url", "default_branch"]
        if not all(data.get(key) for key in required):
            raise ToolError("GitHub returned repository data without required fields.", recoverable=True)

        license_data = data.get("license") or {}
        return RepoInfo(
            owner=owner,
            name=str(data.get("name") or repo),
            full_name=str(data["full_name"]),
            html_url=str(data["html_url"]),
            description=str(data.get("description") or "No description provided."),
            default_branch=str(data["default_branch"]),
            language=str(data.get("language") or "Unknown"),
            stars=int(data.get("stargazers_count") or 0),
            forks=int(data.get("forks_count") or 0),
            open_issues=int(data.get("open_issues_count") or 0),
            license_name=str(license_data.get("spdx_id") or license_data.get("name") or "Not specified"),
            updated_at=str(data.get("updated_at") or "Unknown"),
        )

    def list_tree(self, owner: str, repo: str, branch: str) -> list[dict[str, Any]]:
        branch_ref = urllib.parse.quote(branch, safe="")
        data = self._request_json(f"/repos/{owner}/{repo}/git/trees/{branch_ref}?recursive=1")
        tree = data.get("tree")
        if not isinstance(tree, list):
            raise ToolError("GitHub tree response did not contain a file list.", recoverable=True)
        return [item for item in tree if item.get("type") == "blob"]

    def read_file(self, owner: str, repo: str, path: str, ref: str) -> SourceFile:
        encoded_path = urllib.parse.quote(path, safe="/")
        encoded_ref = urllib.parse.quote(ref, safe="")
        data = self._request_json(f"/repos/{owner}/{repo}/contents/{encoded_path}?ref={encoded_ref}")
        if data.get("encoding") != "base64" or not data.get("content"):
            raise ToolError(f"GitHub did not return base64 content for {path}.", recoverable=True)

        try:
            raw = base64.b64decode(data["content"], validate=False)
        except ValueError as exc:
            raise ToolError(f"Could not decode {path}: {exc}", recoverable=True) from exc

        content = raw.decode("utf-8", errors="replace")
        language = SOURCE_EXTENSIONS.get(PurePosixPath(path).suffix.lower(), "Text")
        return SourceFile(path=path, content=content, size=int(data.get("size") or len(raw)), language=language)

    def repo_exists(self, owner: str, repo: str) -> bool:
        try:
            self._request_json(f"/repos/{owner}/{repo}")
            return True
        except ToolError:
            return False

    def _request_json(self, path: str) -> dict[str, Any]:
        if self.failure_injector.should_fail("github_api"):
            raise ToolError("Simulated GitHub timeout for failure-recovery demo.", recoverable=True)

        if path in self._cache:
            return self._cache[path]

        url = path if path.startswith("http") else f"{self.api_base}{path}"
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            recoverable = exc.code in {408, 429, 500, 502, 503, 504}
            raise ToolError(f"GitHub API returned HTTP {exc.code}: {body}", recoverable=recoverable) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise ToolError(f"GitHub request failed: {exc}", recoverable=True) from exc

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ToolError(f"GitHub returned invalid JSON: {exc}", recoverable=True) from exc
        if not isinstance(data, dict):
            raise ToolError("GitHub returned JSON that was not an object.", recoverable=True)

        self._cache[path] = data
        return data

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "repo-analysis-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers


def choose_source_files(tree: list[dict[str, Any]], max_files: int) -> list[str]:
    """Pick the most interesting source files to analyze.

    Scoring: +25 Python (AST support), +8 shallow path (likely core code),
    +6 in src/app/lib, -5 test files, +0-1 by size.
    """
    candidates: list[tuple[float, str]] = []
    for item in tree:
        path = str(item.get("path") or "")
        size = int(item.get("size") or 0)
        suffix = PurePosixPath(path).suffix.lower()
        if suffix not in SOURCE_EXTENSIONS:
            continue
        if size <= 0 or size > MAX_SOURCE_BYTES:
            continue
        parts = {part.lower() for part in PurePosixPath(path).parts}
        if parts & SKIP_PARTS:
            continue

        lower_path = path.lower()
        score = 0.0
        score += 25 if suffix == ".py" else 0
        score += 8 if path.count("/") <= 1 else 0
        score += 6 if any(p in {"src", "app", "lib"} for p in parts) else 0
        score -= 5 if "test" in lower_path else 0
        score += min(size, 20_000) / 20_000
        candidates.append((score, path))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in candidates[:max_files]]


def tree_has_tests(tree: list[dict[str, Any]]) -> bool:
    for item in tree:
        path = str(item.get("path") or "").lower()
        if path.startswith("test_") or "/test_" in path or "tests/" in path or "/tests/" in path:
            return True
    return False


def tree_has_readme(tree: list[dict[str, Any]]) -> bool:
    return any(str(item.get("path") or "").lower().startswith("readme") for item in tree)


def tree_has_license_file(tree: list[dict[str, Any]]) -> bool:
    names = {"license", "license.md", "license.txt", "copying", "copying.md"}
    return any(str(item.get("path") or "").lower() in names for item in tree)


def tree_has_python_dependency_file(tree: list[dict[str, Any]]) -> bool:
    names = {"requirements.txt", "pyproject.toml", "poetry.lock", "pipfile", "environment.yml", "setup.py"}
    return any(str(item.get("path") or "").lower() in names for item in tree)
