# PR Feedback Loop & Jobs Admin UI — Design Spec

## Goal

Two related features that share a job-tracking foundation:

1. **PR Feedback Loop** — when a reviewer posts `/rework` on an AI-generated PR, re-run the agent on the same branch incorporating the feedback.
2. **Jobs Admin UI** — a `/jobs` page showing recent job history (status, engine, PR link) backed by a SQLite store.

## Architecture

Both features depend on a new `store.py` module that persists job state to SQLite. The worker writes to it at every state transition. The server reads from it for the `/api/jobs` endpoint. The PR comment webhook handlers use the branch name to recover the original issue number without any DB lookup.

```
webhook (PR comment) → server.py → enqueue ReworkJob → worker._process_rework_job
                                                           ↓
                                                        store.py (update status)
                                                           ↓
                                              run_agent (same branch) + force-push
                                                           ↓
                                                  post comment + set ai: done

GET /api/jobs → server.py → store.list_jobs() → JSON response
```

## Tech Stack

- **SQLite** via Python `sqlite3` stdlib — no external dependencies
- **FastAPI** — existing framework, adds one GET endpoint
- **Vanilla JS** — no framework, reuses existing CSS custom properties for light/dark theming

---

## Components

### `store.py` (new)

SQLite file path: `ai_jobs.db` in the same directory as `server.py` (i.e., next to `__file__`).

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    platform      TEXT NOT NULL,
    issue_number  INTEGER NOT NULL,
    issue_title   TEXT NOT NULL,
    engine        TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'queued',
    pr_url        TEXT NOT NULL DEFAULT '',
    error_msg     TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
```

`status` values: `queued`, `processing`, `done`, `failed`, `needs_clarification`, `reworking`

**Public API:**

```python
def init_db(db_path: str) -> None:
    """Create tables if they don't exist. Call once at startup."""

def create_job(db_path: str, *, platform: str, issue_number: int, issue_title: str) -> int:
    """Insert a new job record with status='queued'. Returns the row id."""

def update_job(db_path: str, job_id: int, **fields) -> None:
    """Update any subset of: status, engine, pr_url, error_msg."""

def list_jobs(db_path: str, limit: int = 100) -> list[dict]:
    """Return the most recent `limit` jobs as dicts, newest first."""
```

All functions open and close their own connection — no shared state. Thread-safe via SQLite WAL mode.

---

### `config.py` changes

Add one field after `default_agent`:

```python
admin_password: str = ""  # empty = /api/jobs is open (dev convenience)
```

---

### `worker.py` changes

**`Job` dataclass** — add optional fields:

```python
@dataclass
class Job:
    platform: str
    issue_number: int
    title: str
    body: str
    job_id: int = 0         # 0 = not yet persisted (legacy path)
    pr_branch: str = ""     # set for rework jobs
    rework_comment: str = ""  # set for rework jobs
```

**Module-level settings reference** — `start_worker` stores settings so `enqueue_job` can reach `db_path`:

```python
_settings_ref: Settings | None = None

async def start_worker(settings: Settings) -> None:
    global _settings_ref
    _settings_ref = settings
    ...
```

**`enqueue_job`** — create a DB record and store `job_id` on the `Job`:

```python
async def enqueue_job(*, platform, issue_number, title, body, pr_branch="", rework_comment=""):
    job_id = 0
    if _settings_ref:
        job_id = store.create_job(_settings_ref.db_path, platform=platform,
                                  issue_number=issue_number, issue_title=title)
    await _queue.put(Job(..., job_id=job_id, pr_branch=pr_branch, rework_comment=rework_comment))
```

**`_process_job`** — add `store.update_job(...)` calls at:
- Start: `status="processing"`, `engine=engine.name`
- After PR created: `pr_url=pr_url`
- On done: `status="done"`
- On failed: `status="failed"`, `error_msg=error_msg`
- On needs-clarification: `status="needs_clarification"`

**`_process_rework_job`** (new function) — called when `job.rework_comment` is non-empty:

```python
async def _process_rework_job(job: Job, settings: Settings) -> None:
    platform = create_platform(settings)
    store.update_job(settings.db_path, job.job_id, status="reworking")
    platform.set_label(job.issue_number, _LABEL_PROCESSING)

    issue = platform.get_issue(job.issue_number)
    labels = platform.get_labels(job.issue_number)
    engine = _pick_engine(labels, settings)

    # Get existing diff from the branch before re-running
    repo_path = WORK_DIR / str(job.issue_number)
    # _prepare_repo checks out the existing branch (not creating a new one)
    # branch name comes from pr_branch
    success, repo_path_str, initial_commit, error_msg = await asyncio.to_thread(
        run_agent,
        issue_number=job.issue_number,
        issue_title=issue.title,
        issue_body=_build_rework_body(issue.body, job.rework_comment),
        branch=job.pr_branch,
        settings=settings,
        engine=engine,
        start_ref=f"origin/{job.pr_branch}",  # continue from existing AI work, not default branch
    )

    if not success:
        _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_FAILED)
        store.update_job(settings.db_path, job.job_id,
                         status="failed", error_msg=error_msg)
        platform.post_comment(job.issue_number,
            f"Re-run could not produce passing tests.\n\n```\n{error_msg}\n```")
        return

    await asyncio.to_thread(push_branch, repo_path_str, job.pr_branch, settings,
                            force=True)
    _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_DONE)
    store.update_job(settings.db_path, job.job_id, status="done")
    platform.post_comment(job.issue_number,
        f"Re-run complete. Branch `{job.pr_branch}` updated.")
```

**`_build_rework_body`** (new helper):

```python
def _build_rework_body(original_body: str, rework_comment: str) -> str:
    return (
        f"{original_body}\n\n"
        f"---\n"
        f"**Reviewer feedback (please address):**\n\n"
        f"{rework_comment}"
    )
```

**`run_agent`** in `agent.py` — add `start_ref: str = ""` parameter, passed to `_prepare_repo`. When non-empty, `_prepare_repo` does `git checkout -B branch {start_ref}` so the rework starts from the tip of the existing AI branch (not the repo default branch).

**`push_branch`** in `agent.py` — add `force: bool = False` parameter:

```python
def push_branch(repo_path: str, branch: str, settings: Settings, force: bool = False) -> None:
    ...
    cmd = ["git", "push", "-u", "origin", branch]
    if force:
        cmd.append("--force-with-lease")
    subprocess.run(cmd, cwd=repo_path, check=True, capture_output=True)
```

**`start_worker`** — dispatch to `_process_rework_job` when `job.rework_comment`:

```python
if job.rework_comment:
    await _process_rework_job(job, settings)
else:
    await _process_job(job, settings)
```

---

### `server.py` changes

**Startup** — call `store.init_db(settings.db_path)` in `lifespan`.

**`GET /api/jobs`** — protected by `admin_password`:

```python
@app.get("/api/jobs")
async def api_jobs(request: Request):
    if settings.admin_password:
        token = request.headers.get("X-Admin-Token", "")
        if not hmac.compare_digest(token, settings.admin_password):
            raise HTTPException(status_code=401, detail="Unauthorized")
    return store.list_jobs(settings.db_path)
```

**`POST /webhook/github`** — extend existing handler to detect PR comments:

```python
# New block before the final return {"status": "ignored"}
if action == "created" and "comment" in payload and "issue" in payload:
    issue = payload["issue"]
    if issue.get("pull_request") and "/rework" in payload["comment"].get("body", ""):
        user_type = payload.get("sender", {}).get("type", "")
        if user_type != "Bot":
            pr = issue["pull_request"]
            branch = _extract_branch_from_pr_url(pr.get("url", ""), settings)
            issue_number = _parse_issue_number_from_branch(branch)
            if issue_number:
                background_tasks.add_task(
                    enqueue_job,
                    platform="github",
                    issue_number=issue_number,
                    title=issue.get("title", ""),
                    body=issue.get("body") or "",
                    pr_branch=branch,
                    rework_comment=payload["comment"]["body"],
                )
                return {"status": "queued"}
```

Note: GitHub's `issue_comment` webhook does not include the branch directly. We need to call the GitHub API to get the PR's head branch. Add a helper `_get_github_pr_branch(pr_url, token) -> str` that makes a GET request to the PR API URL.

**`POST /webhook/gitlab`** — extend to handle MR note hooks:

```python
if payload.get("object_kind") == "note":
    attrs = payload.get("object_attributes", {})
    if (attrs.get("noteable_type") == "MergeRequest"
            and "/rework" in attrs.get("note", "")):
        mr = payload.get("merge_request", {})
        branch = mr.get("source_branch", "")
        issue_number = _parse_issue_number_from_branch(branch)
        if issue_number:
            background_tasks.add_task(
                enqueue_job,
                platform="gitlab",
                issue_number=issue_number,
                title=mr.get("title", ""),
                body=mr.get("description") or "",
                pr_branch=branch,
                rework_comment=attrs["note"],
            )
            return {"status": "queued"}
```

**Helpers** (new, in `server.py`):

```python
def _parse_issue_number_from_branch(branch: str) -> int | None:
    """Extract issue number from 'ai/issue-{N}-{slug}' branch name."""
    import re
    m = re.search(r"ai/issue-(\d+)-", branch)
    return int(m.group(1)) if m else None

def _get_github_pr_branch(pr_api_url: str, token: str) -> str:
    """Fetch the PR's head branch name via the GitHub REST API."""
    import urllib.request, json
    req = urllib.request.Request(
        pr_api_url,
        headers={"Authorization": f"token {token}",
                 "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data.get("head", {}).get("ref", "")
```

---

### `config.py` changes

```python
admin_password: str = ""
db_path: str = str(Path(__file__).parent / "ai_jobs.db")
```

---

### `docs_site/jobs.html` (new)

Standalone HTML page. Key behaviors:
- On load: check `sessionStorage.getItem('adminToken')`. If missing, show a password prompt dialog.
- `fetch('/api/jobs', { headers: { 'X-Admin-Token': token } })` — on 401, clear token and re-prompt.
- Renders a `<table>` with columns: Status | Issue | Engine | Created | PR
- Status is a colored pill badge (reuses existing CSS custom property colors from `index.html`)
- Auto-refreshes every 30 seconds via `setInterval`
- Light/dark mode: reads `localStorage.getItem('theme')` and applies `data-theme` to `<html>` (same mechanism as `index.html`)
- No nav sidebar — just a header with a "← Guide" back link and the theme toggle button

---

### `docs_site/index.html` changes

Add "Jobs" link to the sidebar nav:

```html
<a href="/jobs" class="nav-link external">Jobs ↗</a>
```

---

## Data Flow: `/rework` end-to-end

```
1. Reviewer posts "/rework please add error handling" on AI PR
2. GitHub fires issue_comment webhook → POST /webhook/github
3. server.py: detects /rework, calls _get_github_pr_branch → "ai/issue-42-fix-login"
4. _parse_issue_number_from_branch → 42
5. enqueue_job(issue_number=42, pr_branch="ai/issue-42-fix-login",
               rework_comment="/rework please add error handling")
6. worker: job.rework_comment is set → _process_rework_job
7. store.update_job(status="reworking")
8. platform.get_issue(42) → original title + body
9. _build_rework_body: appends reviewer feedback to body
10. run_agent(..., branch="ai/issue-42-fix-login") → agent re-runs on same branch
11. push_branch(..., force=True) → force-pushes to existing PR
12. store.update_job(status="done")
13. platform.post_comment(42, "Re-run complete. Branch `ai/issue-42-fix-login` updated.")
```

---

## Testing

- **`tests/test_store.py`**: `test_create_job`, `test_update_job_status`, `test_list_jobs_newest_first`, `test_list_jobs_respects_limit` — all use `":memory:"` db_path.
- **`tests/test_server.py`**: `test_github_rework_comment_queued`, `test_github_rework_bot_ignored`, `test_gitlab_rework_comment_queued`, `test_api_jobs_no_auth_open`, `test_api_jobs_wrong_token_401`, `test_api_jobs_correct_token_200`.
- **`tests/test_worker.py`**: `test_process_rework_job_success`, `test_process_rework_job_failure`.
- **`tests/test_agent.py`**: `test_push_branch_force_flag`.

---

## Error Handling

- If `_get_github_pr_branch` fails (network error, API rate limit): return `{"status": "ignored"}` and log a warning. Don't crash the webhook handler.
- If `_parse_issue_number_from_branch` returns `None` (non-AI branch): return `{"status": "ignored"}`.
- If rework job fails tests: post failure comment, set `ai: failed`, update DB.
- SQLite errors in `store.py`: log and re-raise — they indicate a configuration problem worth surfacing.
