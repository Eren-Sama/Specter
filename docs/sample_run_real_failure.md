# Sample Run: Real 404 (Repository Not Found)

```bash
python -m repo_agent "Analyze https://github.com/nonexistent/fakerepo123456 for quality issues"
```

```text
USER GOAL
Analyze https://github.com/nonexistent/fakerepo123456 for quality issues

[plan] Analyzed goal and generated 7 steps
PLAN
1. Validate the GitHub repository URL and user goal
2. Gather repository metadata
3. Inspect the repository file tree
4. Read selected source files
5. Run deterministic static analysis
6. Evaluate test presence and structure
7. Validate findings and prepare a structured report

EXECUTION
[fail] Repository nonexistent/fakerepo123456 returned 404
[fail] Repository nonexistent/fakerepo123456 was not found on GitHub. Check the URL for typos or ensure it is public.
```

The agent checks if the repo exists before starting analysis. Real GitHub 404, not a synthetic `--demo-failure`.
