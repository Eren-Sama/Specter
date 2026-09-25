# Write-Up

## Design Decisions

I went with GitHub repository analysis because it's a natural fit — the agent gets live data from a real API, uses multiple tools, and the results are verifiable. Everything runs on the Python standard library so there's nothing to install.

The core idea is that the agent is deterministic. URL parsing, API calls, retries, file selection, AST checks, report generation — all of that is normal Python. The optional LLM summarizer only kicks in if you set `GROQ_API_KEY`, and even then it just rephrases the findings that the tools already collected. So the project works fine without any paid services.

### Why no dependencies

Not laziness — it's deliberate. A reviewer can clone and run `python -m repo_agent` instantly. No venv, no version conflicts, no pip install. The only optional dep is Pillow for generating the terminal screenshots.

### Why AST instead of regex

Regex would've been quicker to write but it can't do structural analysis. You can't reliably measure nesting depth or function length with regex. Python's `ast` module gives you the actual parse tree for free.

### File selection scoring

`choose_source_files` uses a scoring heuristic to pick which files to analyze:

- +25 Python files (we can do AST analysis on these)
- +8 shallow/top-level files (more likely to be core code)
- +6 files in `src/`, `app/`, `lib/`
- -5 test files (still included, just lower priority)
- +0–1 based on file size (slight preference for bigger files)

I tuned these by running the agent on a few open-source repos and checking which files it picked.

## Goal-Dependent Planning

The plan isn't hardcoded. `_build_plan()` looks at keywords in the goal to decide what steps to include:

- "code quality" / "analyze" → full source-file reading + static analysis
- "test" / "coverage" → adds a test-health evaluation step
- "dependencies" / "CI" → adds dependency/CI inspection
- "stars" / "metadata" → skips code analysis entirely

So `"Analyze flask for code quality"` and `"Give me stars and forks for flask"` produce different plans.

## Failure Handling

The `--demo-failure` flag injects a simulated timeout on the first API call. The retry wrapper catches it, waits with exponential backoff (1s, then 2s), and retries.

But the agent also handles real failures:
- **404:** Checks if the repo exists before doing anything else. Gives a clear error, not a stack trace.
- **429 rate limit:** Marked recoverable, retried with backoff so we're not hammering the API.
- **Network errors / bad JSON:** Caught and retried.

The retry strategy is exponential backoff: `delay = base_delay × 2^(attempt-1)`. Default is 3 attempts with 1s base.

## Limitations

The static analyzer is intentionally simple. It catches broad exceptions, long functions, TODO markers, syntax errors, missing tests, deep nesting. These are useful signals but they're not guaranteed bugs.

The agent only looks at a limited number of files per run to stay fast and avoid rate limits. A production version would need deeper scans, more language support, and persistent caching.

## What I'd Do With More Time

- Web UI for easier use
- Local repo support (not just GitHub)
- Deeper dependency and CI inspection
- Tree-sitter for multi-language AST support
- Persistent disk cache across runs
- Snapshot-based integration tests
