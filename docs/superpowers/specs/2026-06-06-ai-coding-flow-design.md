# AI Coding Flow — Design Spec
**Date:** 2026-06-06
**Status:** Approved

## Overview

An autonomous AI coding workflow that watches GitHub and GitLab for new issues, writes code to resolve them, runs tests, creates a PR/MR, and posts a review comment — all without human intervention. The human's only action is deciding whether to merge.

## Goals

- Trigger on issue creation (GitHub or GitLab)
- Fully autonomous: code → test → PR/MR → review comment
- Retry on test failure up to N times; leave a comment if exhausted
- Run fully offline (local LLM via OpenAI-compatible endpoint, GitLab can be self-hosted)
- Start with a single Python repo; generalize to any language later

## Non-Goals

- Auto-merging PRs/MRs
- Handling issue updates or comments (only "issue opened" events)
- Supporting non-Python repos in this iteration
- Parallelizing multiple issues simultaneously (sequential queue for now)

---

## Architecture

```
GitHub/GitLab Issue Created
         │
         ▼ (webhook POST)
  FastAPI Webhook Server
  /webhook/github  /webhook/gitlab
         │
         ▼ (verify signature, enqueue, return 200 immediately)
  In-Process Job Queue (asyncio)
         │
         ▼
  Worker picks up job
  ┌──────────────────────────────────────────┐
  │  1. Clone/pull repo → temp dir           │
  │  2. Create branch: ai/issue-{n}-{slug}   │
  │  3. Run Aider agent with issue text      │
  │     - Aider builds repo-map              │
  │     - Writes code, runs pytest           │
  │     - Auto-fixes on test failure         │
  └──────────────────────────────────────────┘
         │
    ┌────┴────┐
  pass      fail (exhausted)
    │            │
    ▼            ▼
  Push branch   Post comment on issue
  Create PR/MR  Leave issue open
    │
    ▼
  Review Agent (fresh LLM session)
  Posts review comment on PR/MR
    │
    ▼
  Human reviews, clicks Merge
```

---

## Components

### Directory Structure

```
ai-coding-flow/
├── server.py           # FastAPI app — webhook endpoints, signature verification
├── worker.py           # Asyncio job queue — processes issues one at a time
├── agent.py            # Aider wrapper — clones repo, runs coding loop, handles retries
├── reviewer.py         # Review agent — fresh LLM call on the final diff
├── platforms/
│   ├── __init__.py
│   ├── base.py         # Abstract GitPlatform (get_issue, create_branch, create_pr, post_comment)
│   ├── github.py       # PyGitHub implementation
│   └── gitlab.py       # python-gitlab implementation
├── config.py           # Pydantic-settings — all config from .env
├── .env.example
└── requirements.txt
```

### Dependencies

| Package | Purpose |
|---|---|
| `fastapi` + `uvicorn` | Webhook server |
| `aider-chat` | AI coding engine (tool-calling loop, repo-map, test runner) |
| `openai` | LLM client (points to local endpoint) |
| `PyGitHub` | GitHub API |
| `python-gitlab` | GitLab API |
| `pydantic-settings` | Config from `.env` |

---

## Configuration

`.env.example`:
```
PLATFORM=github                            # or: gitlab
REPO_URL=https://github.com/owner/repo    # or self-hosted GitLab URL
GITHUB_TOKEN=ghp_...                       # or GITLAB_TOKEN=...
WEBHOOK_SECRET=your-secret
OPENAI_API_BASE=http://localhost:11434/v1  # local LLM endpoint
OPENAI_API_KEY=local                       # dummy value for local endpoints
OPENAI_MODEL=qwen2.5-coder:32b
MAX_RETRIES=3
TEST_CMD=pytest
```

---

## Data Flow & Sequence

### 1. Webhook Received
- `POST /webhook/github` or `/webhook/gitlab`
- Verify HMAC signature — reject with 403 if invalid
- Check event type — only process "issue opened", return 200 and ignore all others
- Enqueue job: `{platform, repo, issue_number, title, body}`
- Return 200 immediately (platform requires fast response)

### 2. Worker Picks Up Job
- Clone repo to `/tmp/ai-coding-flow/{issue_number}/`
- If already cloned, `git pull` instead
- Create branch: `ai/issue-{number}-{title-slug}`

### 3. Aider Agent Loop
- Build repo-map (Aider scans repo, builds symbol index for context selection)
- Prompt: issue title + body + instruction to write code and tests
- Aider internally:
  1. Selects relevant files via repo-map
  2. Asks LLM to edit files
  3. Runs `TEST_CMD` (default: `pytest`)
  4. If tests fail → feeds failure output back to LLM → retries
  5. Stops when tests pass or `MAX_RETRIES` test-fix cycles are exhausted
- `MAX_RETRIES` (default: 3) controls the maximum number of test-fix cycles Aider will attempt before giving up

### 4a. Success Path
- `git push` branch to remote
- Create PR (GitHub) or MR (GitLab):
  - Title: `fix: {issue title} (resolves #{number})`
  - Body: links issue, summarizes changes
- Run Review Agent (fresh LLM session):
  - Input: issue body + `git diff` of branch vs main
  - Output: structured review comment
- Post review comment on PR/MR

### 4b. Failure Path
- Post comment on issue:
  > "AI attempted to fix this issue but could not produce passing tests after {N} attempts. Last error: {snippet}"
- Leave issue open
- Clean up temp directory

---

## Platform Abstraction

`GitPlatform` base class interface:

```python
class GitPlatform(ABC):
    def get_issue(self, number: int) -> Issue: ...
    def create_branch(self, name: str) -> None: ...
    def push_branch(self, name: str) -> None: ...
    def create_pr(self, branch: str, title: str, body: str) -> str: ...  # returns PR/MR URL
    def post_comment(self, issue_number: int, body: str) -> None: ...
    def get_diff(self, branch: str) -> str: ...
```

`GitHubPlatform` uses `PyGitHub`.
`GitLabPlatform` uses `python-gitlab`.
Both are instantiated at startup based on `PLATFORM` env var.

---

## Error Handling

| Failure Point | Behavior |
|---|---|
| Invalid webhook signature | Return 403, log warning |
| Non "issue opened" event | Return 200, ignore |
| Repo clone fails | Post comment on issue with error message |
| Aider exhausts retries | Post comment on issue with last test failure snippet |
| LLM endpoint unreachable | Post comment on issue: "LLM endpoint unavailable" |
| PR/MR creation fails | Post comment on issue with error; branch is left pushed |
| Review agent fails | Log only — PR/MR still exists, review is best-effort |
| Unhandled exception | Always post comment on issue; never silently drop |

---

## Testing Strategy

### Unit Tests (no network, no LLM)
- Webhook HMAC signature verification
- Webhook payload parsing (issue opened vs other events)
- Platform abstraction with mocked `GitPlatform`
- Config validation (missing fields, invalid platform)
- Branch name slug generation

### Integration Tests (manual, requires real services)
- End-to-end: post test issue to sandbox repo, verify PR/MR appears
- Aider loop against local LLM with a toy Python repo
- GitLab MR creation against self-hosted GitLab instance

---

## Future Extensions
- Support any language (remove Python-only constraint, make `TEST_CMD` the only language coupling)
- Parallel workers (`MAX_WORKERS` env var)
- Handle issue comments as re-trigger (`/retry` comment)
- Bitbucket / Gitea support (add new `GitPlatform` implementation)
