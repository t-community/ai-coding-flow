# Multi-Repo Support Design

**Date:** 2026-06-09  
**Status:** Approved

## Problem

The system is currently hardcoded for a single repository via `PLATFORM` and `REPO_URL` environment variables. To serve multiple repos, operators had to run separate instances. The goal is to allow a single instance to handle webhooks from any number of repositories, with repo identity derived dynamically from the webhook payload.

## Approach

Remove the single-repo config from `Settings`. Extract `repo_url` and `platform` from each incoming webhook payload. Thread both values through the job pipeline — `Job` dataclass, `enqueue_job`, `create_platform`, `run_agent`, `push_branch` — so every downstream operation acts on the correct repository. Authentication remains via single global tokens per platform (`GITHUB_TOKEN`, `GITLAB_TOKEN`).

## Architecture

### `config.py` — Remove repo-specific fields

`platform: Literal["github", "gitlab"]` and `repo_url: str` are removed from `Settings`. All remaining settings (tokens, engine config, workflow settings) are global and apply to all repos.

### `server.py` — Payload extraction

On every webhook event, extract the repo URL before calling `enqueue_job`:

- **GitHub**: `payload.get("repository", {}).get("clone_url", "")` — present on all GitHub event types
- **GitLab**: `payload.get("project", {}).get("http_url_to_repo", "")` — present on all GitLab event types

Both `repo_url` and `platform` are passed to every `enqueue_job(...)` call.

If either is missing (malformed payload), the endpoint returns `{"status": "ignored"}`.

### `worker.py` — Job carries repo identity

`Job` dataclass gains `repo_url: str`. `enqueue_job` accepts `repo_url` and `platform` and stores them on the `Job`.

`_process_job` and `_process_rework_job` pass `job.repo_url` and `job.platform` to:
- `create_platform(job.platform, job.repo_url, settings)`
- `run_agent(..., repo_url=job.repo_url, platform=job.platform)`
- `push_branch(..., repo_url=job.repo_url, platform=job.platform)`

The exception handler in `start_worker` also uses `job.platform` and `job.repo_url` to construct the platform for error reporting.

### `platforms/__init__.py` — Explicit params

```python
def create_platform(platform: str, repo_url: str, settings) -> GitPlatform:
```

No longer reads `settings.platform` or `settings.repo_url`.

### `agent.py` — Explicit repo params

`run_agent` and `push_branch` accept `repo_url: str` and `platform: str` as explicit params. `_authenticated_url` takes them directly instead of reading from `settings`.

**Work-dir collision fix:** Currently `WORK_DIR / str(issue_number)`. Two repos with issue #42 would share a work dir. Changed to `WORK_DIR / f"{_repo_slug(repo_url)}-{issue_number}"` where `_repo_slug` derives `owner-repo` from the URL path.

```python
def _repo_slug(repo_url: str) -> str:
    path = urlparse(repo_url).path.strip("/").removesuffix(".git")
    return re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
```

### `store.py` — DB migration

`init_db` adds `repo_url TEXT NOT NULL DEFAULT ''` column via `ALTER TABLE ... ADD COLUMN` (wrapped in try/except for idempotency on existing DBs). `create_job` accepts and stores `repo_url`.

## Data Flow

```
Webhook arrives
  → server.py extracts (platform, repo_url) from payload
  → enqueue_job(platform, repo_url, issue_number, ...)
  → Job(platform, repo_url, ...)
  → _process_job(job, settings)
      → create_platform(job.platform, job.repo_url, settings)
      → run_agent(..., repo_url=job.repo_url, platform=job.platform)
      → push_branch(..., repo_url=job.repo_url, platform=job.platform)
```

## `.env.example` Cleanup

Remove:
```
PLATFORM=github
REPO_URL=https://github.com/t-community/demo-repository
```

## Test Changes

- **`test_config.py`**: Remove all `PLATFORM`/`REPO_URL` env vars and constructor args. Delete `test_invalid_platform_raises` and `test_missing_platform_raises` (those fields no longer exist).
- **`test_server.py`**: Remove `PLATFORM`/`REPO_URL` from the autouse fixture. Add `repository: {clone_url: ...}` to all GitHub test payloads. Add `project: {http_url_to_repo: ...}` to all GitLab test payloads. Assert `repo_url` and `platform` are present in `enqueue_job` kwargs.
- **`test_worker.py`**: Add `repo_url="https://github.com/owner/repo"` to all `Job(...)` instantiations.

## What Does Not Change

- Webhook endpoints remain `/webhook/github` and `/webhook/gitlab` (no per-repo routing needed)
- `GITHUB_TOKEN`, `GITLAB_TOKEN`, `WEBHOOK_SECRET` remain global
- All engine/workflow settings (`DEFAULT_AGENT`, `TEST_CMD`, `MAX_RETRIES`, etc.) remain global
- No per-repo config file (deferred)
