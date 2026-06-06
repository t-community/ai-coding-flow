# AI Coding Flow

An autonomous AI coding workflow that watches GitHub and GitLab for new issues, writes code to resolve them, runs tests, opens a PR/MR, and posts a review comment — all without human intervention. The only human action required is deciding whether to merge.

```
Issue Created → Webhook → AI Codes + Tests → PR/MR Opened → Review Comment Posted
```

## Features

- **GitHub & GitLab** — unified abstraction, works with both platforms (including self-hosted GitLab)
- **Retry loop** — re-prompts the AI with test failure output up to `MAX_RETRIES` times
- **AI code review** — after the PR is created, a fresh LLM call reviews the diff and posts a structured comment
- **Offline-capable** — works with any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, etc.)
- **Sequential queue** — processes one issue at a time to avoid git conflicts

## How It Works

1. A GitHub/GitLab webhook fires when a new issue is opened
2. The server verifies the signature and enqueues the job
3. A worker clones the repo to a temp directory, creates a branch `ai/issue-{n}-{slug}`
4. [Aider](https://aider.chat) runs against the issue text, writes code, and runs your test suite
5. On test failure, the error output is fed back to the LLM and Aider retries (up to `MAX_RETRIES`)
6. On success: the branch is pushed, a PR/MR is created, and a review comment is posted
7. On exhausted retries: a comment is posted on the issue explaining what failed

## Quick Start

### Prerequisites

- Python 3.10+
- A GitHub or GitLab account with a repo that has a `pytest` test suite
- An OpenAI-compatible LLM endpoint (e.g., [Ollama](https://ollama.com))
- A way to expose your local server (e.g., [ngrok](https://ngrok.com))

### Install

```bash
git clone https://github.com/your-org/ai-coding-flow.git
cd ai-coding-flow
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env with your values
```

| Variable | Description |
|---|---|
| `PLATFORM` | `github` or `gitlab` |
| `REPO_URL` | Full HTTPS URL of the target repo |
| `GITHUB_TOKEN` | Personal access token (repo scope) |
| `GITLAB_TOKEN` | Personal access token (api scope) |
| `WEBHOOK_SECRET` | Random string — must match your webhook config |
| `OPENAI_API_BASE` | Your LLM endpoint, e.g. `http://localhost:11434/v1` |
| `OPENAI_API_KEY` | `local` for offline endpoints |
| `OPENAI_MODEL` | Model name, e.g. `qwen2.5-coder:32b` |
| `MAX_RETRIES` | Max test-fix cycles before giving up (default: `3`) |
| `TEST_CMD` | Command to run tests (default: `pytest`) |

### Run the Server

```bash
uvicorn server:app --env-file .env --port 8000
```

### Expose via ngrok

```bash
ngrok http 8000
```

### Register the Webhook

**GitHub:**
- Go to your repo → Settings → Webhooks → Add webhook
- Payload URL: `https://<your-ngrok-url>/webhook/github`
- Content type: `application/json`
- Secret: your `WEBHOOK_SECRET`
- Events: select **Issues** only

**GitLab:**
- Go to your repo → Settings → Webhooks
- URL: `https://<your-ngrok-url>/webhook/gitlab`
- Secret Token: your `WEBHOOK_SECRET`
- Trigger: **Issues events** only

### Test It

Create an issue in your target repo. Within seconds the worker will pick it up, run Aider, and (if tests pass) open a PR with a review comment.

## Docker

```bash
docker build -t ai-coding-flow .
docker run --env-file .env -p 8000:8000 ai-coding-flow
```

## Architecture

```
GitHub/GitLab Issue Created
         │
         ▼ (webhook POST)
  FastAPI Webhook Server
  /webhook/github  /webhook/gitlab
         │
         ▼ (verify signature, enqueue, return 200)
  asyncio Job Queue
         │
         ▼
  Worker (one issue at a time)
  ┌─────────────────────────────────┐
  │  Clone/pull repo → /tmp/        │
  │  Create branch ai/issue-{n}-…   │
  │  Run Aider with issue text      │
  │  Run TEST_CMD                   │
  │  Retry up to MAX_RETRIES times  │
  └─────────────────────────────────┘
         │
    ┌────┴────┐
  pass      fail
    │            └── post comment on issue
    ▼
  Push branch → Create PR/MR → Review Agent → Post review comment
```

**Key files:**

| File | Purpose |
|---|---|
| `server.py` | FastAPI app, webhook endpoints, HMAC verification |
| `worker.py` | asyncio job queue, orchestrates each issue |
| `agent.py` | Aider wrapper, clone/push helpers, retry loop |
| `reviewer.py` | Fresh LLM call to review the final diff |
| `platforms/` | GitHub + GitLab abstraction |
| `config.py` | Pydantic-settings, all config from `.env` |

## Development

```bash
# Run tests
pytest tests/ -v

# Type check
pip install mypy
mypy .

# Lint
pip install ruff
ruff check .
```

## License

MIT
