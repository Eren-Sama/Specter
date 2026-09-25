# Write-Up

## Design Decisions

I chose GitHub repository analysis because it fits the requirements naturally. The agent pulls live data from a real API, uses different tools, and you can easily verify the results. I built everything using the Python standard library, so you don't need to install anything.

The core agent is completely deterministic. All the URL parsing, API calls, file selection, AST checks, and report generation run on plain Python. There is an optional LLM summarizer that only runs if you set the `GROQ_API_KEY` environment variable. Even then, it just reformats the findings the tools already gathered. The project runs perfectly fine without relying on paid APIs.

### Why no dependencies

This was a deliberate choice. I wanted a reviewer to be able to clone the repo and immediately run `python -m repo_agent`. You don't have to deal with virtual environments, pip installs, or version conflicts. The only optional dependency is Pillow, which I just used to generate the terminal screenshots for the docs.

### Why AST instead of regex

Writing some regex patterns would have been faster, but regex is terrible for structural analysis. You simply can't rely on it to measure things like nesting depth or function length. Python's built-in `ast` module provides the exact parse tree for free.

### File selection scoring

The `choose_source_files` function uses a basic scoring system to decide which files to look at:

* +25 Python files (since we can run AST checks on them)
* +8 shallow or top-level files (these usually contain core code)
* +6 files sitting in `src/`, `app/`, or `lib/`
* -5 test files (they are still included, but given lower priority)
* +0 to 1 based on file size (larger files get a slight bump)

I tweaked these numbers by running the agent against a few random open-source repos to see what it naturally grabbed.

## Goal-Dependent Planning

The execution plan is not hardcoded. The `_build_plan()` method checks the user's goal for specific keywords and adjusts the steps accordingly:

* "code quality" or "analyze" triggers full source file reading and static analysis
* "test" or "coverage" adds a step to evaluate test health
* "dependencies" or "CI" adds a check for dependency and CI configs
* "stars" or "metadata" skips the code analysis entirely

If you ask to "Analyze flask for code quality," you get a completely different plan than if you ask for "stars and forks for flask."

## Failure Handling

You can pass the `--demo-failure` flag to inject a fake timeout on the very first API call. The retry wrapper will catch it, wait using exponential backoff (1s, then 2s), and try again.

The agent handles real failures too:
* **404:** It checks if the repo actually exists before starting. If it doesn't, you get a clean error message instead of a stack trace.
* **429 rate limit:** This is flagged as recoverable and retried with backoff so the API doesn't get hammered.
* **Network errors or bad JSON:** These get caught and retried automatically.

The backoff math is simple: `delay = base_delay * 2^(attempt-1)`. By default it makes 3 attempts starting with a 1-second delay.

## Limitations

The static analyzer is pretty basic on purpose. It looks for broad exceptions, long functions, TODO comments, syntax errors, missing tests, and deep nesting. These are good hints for code quality, but they aren't guaranteed to be bugs.

The agent also limits how many files it checks per run. This keeps things fast and helps avoid rate limits. A real production version would need deeper scanning, support for more languages, and a solid caching layer.

## What I'd Do With More Time

* Build a web UI to make it easier to use
* Add support for local directories instead of just GitHub repos
* Write deeper checks for dependencies and CI pipelines
* Integrate Tree-sitter so we could do AST analysis on multiple languages
* Save cache to disk so it persists across runs
* Add snapshot-based integration tests
