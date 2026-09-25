# Rubric Checklist

Maps each assignment requirement to where it's implemented.

## Problem Decomposition & Planning (20%)

`_build_plan()` in `agent.py` generates a goal-dependent plan:

- Code-quality goals → source reading + static analysis steps
- Test/coverage goals → adds test-health evaluation
- Dependency/CI goals → adds dependency inspection
- Metadata-only goals → skips code analysis

Tests: `test_plan_is_goal_dependent`, `test_plan_includes_test_step_for_quality_goal`

## Tool Use & Orchestration (20%)

Three tools:

- `GitHubTool` — live GitHub API with response caching
- `StaticAnalyzer` — Python AST + text checks
- `OptionalLLMSummarizer` — optional, only when `GROQ_API_KEY` is set

Every tool call is timed and logged.

## Robustness & Error Handling (20%)

**Simulated failure:**

```bash
python -m repo_agent "Analyze https://github.com/Eren-Sama/PulmoVision" --demo-failure --max-files 5 --no-llm
```

First API call raises a recoverable `ToolError`, agent waits (exponential backoff), retries, continues.

**Real failures:**

- 404 → `repo_exists()` check before analysis, clear error message
- 429 rate limit → recoverable, retried with backoff
- Network errors → caught and retried
- Bad JSON → caught as recoverable

```bash
python -m repo_agent "Analyze https://github.com/nonexistent/fakerepo123456"
```

Tests: `test_recovery_after_failed_tool_call`, `test_nonexistent_repo_raises`, `test_all_retries_exhausted_raises`, `test_llm_summarizer_failure_is_handled`

## Code Quality & Structure (15%)

- Clean module separation: models, tools, agent, reporting, CLI
- `unittest.mock` with `spec=GitHubTool` so tests break if the interface changes
- 20 tests covering planning, recovery, retry exhaustion, LLM integration, serialization, analysis, file selection
- Local fixture for offline testing
- Zero external dependencies

## Documentation & Communication (15%)

- `README.md` — setup, all features, test list
- `docs/architecture.md` — component + sequence diagrams
- `docs/writeup.md` — design decisions and trade-offs
- `docs/sample_run_*.md` — terminal transcripts
- This file

## Creativity & Initiative (10%)

- Structured logging (`--log-file`, `--verbose`)
- Agent self-evaluation (`--evaluate`)
- Goal-dependent planning (not a static pipeline)
- Exponential backoff for retries
- Response caching
- Per-call timing
- Real 404 handling
