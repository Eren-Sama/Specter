# Architecture

```mermaid
flowchart TD
    A[User goal from CLI] --> B[RepoAnalysisAgent]
    B --> C[Goal-dependent planning]
    C --> D[GitHub API tool]
    D --> E[Repository metadata]
    D --> F[Repository tree]
    D --> G[Selected source files]
    G --> H[Python static analyzer]
    H --> I[Finding validator]
    I --> J[Markdown and JSON report]
    B --> K[Retry with exponential backoff]
    K --> D
    I --> L[Optional LLM summarizer]
    L --> J
```

## Retry flow

```mermaid
sequenceDiagram
    participant User
    participant Agent
    participant GitHubAPI
    participant Analyzer

    User->>Agent: "Analyze github.com/org/repo"
    Agent->>Agent: Build goal-dependent plan
    Agent->>GitHubAPI: Fetch metadata (attempt 1)
    GitHubAPI-->>Agent: ❌ 503 Service Unavailable
    Agent->>Agent: Log failure, wait 1.0s (backoff)
    Agent->>GitHubAPI: Fetch metadata (attempt 2)
    GitHubAPI-->>Agent: ✅ 200 OK
    Agent->>GitHubAPI: Fetch tree
    GitHubAPI-->>Agent: ✅ 200 OK
    Agent->>GitHubAPI: Read files (×N)
    Agent->>Analyzer: Static analysis
    Analyzer-->>Agent: Findings[]
    Agent->>Agent: Validate & build report
    Agent-->>User: Markdown + JSON report
```

## Components

- **RepoAnalysisAgent** — orchestrates everything: planning, tool calls, retries, validation, report.
- **GitHubTool** — GitHub REST API wrapper with caching.
- **StaticAnalyzer** — text checks + Python AST checks.
- **FailureInjector** — simulates transient failures for demos.
- **reporting.py** — converts results into Markdown and JSON.
- **OptionalLLMSummarizer** — optional Groq API call for nicer wording.
- **logger.py** — structured logging (console + JSON file).
