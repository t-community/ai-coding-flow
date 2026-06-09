# Multi-Repo Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the single-repo `PLATFORM`/`REPO_URL` env config and instead extract repo identity from each incoming webhook payload, allowing one running instance to serve any number of repositories.

**Architecture:** `platform` and `repo_url` are stripped from `Settings` and instead pulled from each webhook event (`repository.clone_url` for GitHub, `project.http_url_to_repo` for GitLab). Both values ride on the `Job` dataclass through the entire pipeline and are passed explicitly to `create_platform`, `run_agent`, and `push_branch`. Authentication stays via the global `GITHUB_TOKEN` / `GITLAB_TOKEN` settings.

**Tech Stack:** Python 3.13, FastAPI, Pydantic Settings v2, SQLite (via `sqlite3`), PyGithub, python-gitlab

---

## File Map

| File | Change |
|------|--------|
| `config.py` | Remove `platform` and `repo_url` fields |
| `store.py` | Add `repo_url` column + ALTER TABLE migration; update `create_job` |
| `agent.py` | Add `_repo_slug`; update `run_agent`, `push_branch`, `_authenticated_url`, `_prepare_repo` to take explicit `repo_url` and `platform` args |
| `platforms/__init__.py` | Change to `create_platform(platform, repo_url, settings)` |
| `worker.py` | Add `repo_url: str` to `Job`; update `enqueue_job`, `_process_job`, `_process_rework_job`, and the exception handler |
| `server.py` | Extract `repo_url` and `platform` from every webhook payload before calling `enqueue_job` |
| `.env.example` | Remove `PLATFORM=` and `REPO_URL=` lines |
| `tests/test_config.py` | Remove all `platform`/`repo_url` refs; delete two tests that no longer apply |
| `tests/test_store.py` | Pass `repo_url` to `create_job`; add assertion it is stored |
| `tests/test_agent.py` | Update `_settings` helper and all `_authenticated_url`, `run_agent`, `push_branch` call sites |
| `tests/test_server.py` | Add `repository`/`project` keys to all fixture payloads; remove `PLATFORM`/`REPO_URL` from fixtures; assert `repo_url` and `platform` forwarded to `enqueue_job` |
| `tests/test_worker.py` | Add `repo_url` to every `Job(...)` instantiation |

---

### Task 1: Slim down Settings — remove platform and repo_url

**Files:**
- Modify: `config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Update test_config.py to reflect the new Settings shape**

Replace the entire `tests/test_config.py` with:

```python
import pytest
from pydantic import ValidationError


def test_valid_config(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "secret123")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    from config import Settings
    s = Settings(_env_file=None)
    assert s.max_retries == 3
    assert s.test_cmd == ""
    assert s.openai_api_key == "local"


def test_missing_webhook_secret_raises(monkeypatch):
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    with pytest.raises(ValidationError):
        from config import Settings
        Settings(_env_file=None)


def test_default_agent_defaults_to_aider():
    from config import Settings
    s = Settings(
        webhook_secret="secret",
        openai_api_base="http://localhost/v1",
        _env_file=None,
    )
    assert s.default_agent == "aider"


def test_default_agent_can_be_set():
    from config import Settings
    s = Settings(
        webhook_secret="secret",
        openai_api_base="http://localhost/v1",
        default_agent="opencode",
        _env_file=None,
    )
    assert s.default_agent == "opencode"


def test_admin_password_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("WEBHOOK_SECRET", "s")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost/v1")
    from importlib import reload
    import config
    reload(config)
    s = config.Settings()
    assert s.admin_password == ""


def test_openai_model_strips_surrounding_quotes():
    from config import Settings
    s = Settings(
        webhook_secret="secret",
        openai_api_base="http://localhost/v1",
        openai_model='"openai/gpt-4o"',
        _env_file=None,
    )
    assert s.openai_model == "openai/gpt-4o"


def test_openai_model_strips_single_quotes():
    from config import Settings
    s = Settings(
        webhook_secret="secret",
        openai_api_base="http://localhost/v1",
        openai_model="'qwen2.5-coder:32b'",
        _env_file=None,
    )
    assert s.openai_model == "qwen2.5-coder:32b"


def test_db_path_defaults_to_ai_jobs_db(monkeypatch):
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.setenv("WEBHOOK_SECRET", "s")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost/v1")
    from importlib import reload
    import config
    reload(config)
    s = config.Settings()
    assert s.db_path.endswith("ai_jobs.db")


def test_settings_has_no_platform_field():
    from config import Settings
    s = Settings(
        webhook_secret="secret",
        openai_api_base="http://localhost/v1",
        _env_file=None,
    )
    assert not hasattr(s, "platform")


def test_settings_has_no_repo_url_field():
    from config import Settings
    s = Settings(
        webhook_secret="secret",
        openai_api_base="http://localhost/v1",
        _env_file=None,
    )
    assert not hasattr(s, "repo_url")
```

- [ ] **Step 2: Run the tests — they should fail**

```bash
cd /home/neverleave0916/workspace/ai-test && python -m pytest tests/test_config.py -v 2>&1 | tail -20
```

Expected: several failures because `Settings` still has `platform` and `repo_url`.

- [ ] **Step 3: Update config.py**

Replace the entire `config.py` with:

```python
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    github_token: str = ""
    gitlab_token: str = ""
    webhook_secret: str
    verbose: bool = False
    verify_repo_ssl: bool = True
    verify_engine_ssl: bool = True
    openai_api_base: str
    openai_api_key: str = "local"
    openai_model: str = "qwen2.5-coder:32b"

    @field_validator("openai_model", mode="before")
    @classmethod
    def strip_model_quotes(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip("\"'")
        return v

    max_retries: int = 3
    test_cmd: str = ""
    agent_timeout: int = 600
    default_agent: str = "aider"

    aider_verbose: bool = False
    aider_map_tokens: int = 2048
    aider_token_budget: int = 80000

    opencode_context_limit: int = 32768
    opencode_output_limit: int = 4096

    claudecode_router_port: int = 3456
    claudecode_router_startup_timeout: int = 15

    admin_password: str = ""
    db_path: str = str(Path(__file__).parent / "ai_jobs.db")

    model_config = {"env_file": ".env"}
```

- [ ] **Step 4: Run tests — all test_config.py should pass**

```bash
python -m pytest tests/test_config.py -v 2>&1 | tail -20
```

Expected: all green.

- [ ] **Step 5: Run the full suite to check nothing else broke**

```bash
python -m pytest --tb=short 2>&1 | tail -30
```

Expected: same pass/fail count as before this task (server tests still use monkeypatched PLATFORM/REPO_URL env vars but Settings now ignores them — no error).

- [ ] **Step 6: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: remove platform and repo_url from Settings"
```

---

### Task 2: Add repo_url to job store

**Files:**
- Modify: `store.py`
- Modify: `tests/test_store.py`

- [ ] **Step 1: Add a failing test for repo_url storage**

Add the following test to the bottom of `tests/test_store.py`:

```python
def test_create_job_stores_repo_url(db):
    store.create_job(
        db,
        platform="github",
        repo_url="https://github.com/owner/repo.git",
        issue_number=1,
        issue_title="Fix bug",
    )
    jobs = store.list_jobs(db)
    assert jobs[0]["repo_url"] == "https://github.com/owner/repo.git"
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_store.py::test_create_job_stores_repo_url -v
```

Expected: FAIL — `create_job` does not accept `repo_url` yet.

- [ ] **Step 3: Update store.py**

Replace the entire `store.py` with:

```python
import sqlite3
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def init_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                platform     TEXT NOT NULL,
                repo_url     TEXT NOT NULL DEFAULT '',
                issue_number INTEGER NOT NULL,
                issue_title  TEXT NOT NULL,
                engine       TEXT NOT NULL DEFAULT '',
                status       TEXT NOT NULL DEFAULT 'queued',
                pr_url       TEXT NOT NULL DEFAULT '',
                error_msg    TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
        """)
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN repo_url TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass


def create_job(
    db_path: str,
    *,
    platform: str,
    issue_number: int,
    issue_title: str,
    repo_url: str = "",
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO jobs (platform, repo_url, issue_number, issue_title, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (platform, repo_url, issue_number, issue_title, now, now),
        )
        return cur.lastrowid


def update_job(db_path: str, job_id: int, **fields) -> None:
    allowed = {"status", "engine", "pr_url", "error_msg"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    now = datetime.now(timezone.utc).isoformat()
    updates["updated_at"] = now
    cols = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [job_id]
    with sqlite3.connect(db_path) as conn:
        result = conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", values)
        if result.rowcount == 0:
            logger.warning("update_job: no row with id=%d", job_id)


def list_jobs(db_path: str, limit: int = 100) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: Run test_store.py — all should pass**

```bash
python -m pytest tests/test_store.py -v
```

Expected: all green including the new `test_create_job_stores_repo_url`.

- [ ] **Step 5: Commit**

```bash
git add store.py tests/test_store.py
git commit -m "feat: add repo_url column to jobs table with migration"
```

---

### Task 3: Update agent.py — explicit repo params

**Files:**
- Modify: `agent.py`
- Modify: `tests/test_agent.py`

Background: `_authenticated_url`, `push_branch`, `run_agent`, and `_prepare_repo` all currently read `settings.platform` and `settings.repo_url`. After this task they take those two values as explicit parameters instead. We also add `_repo_slug` and fix the work-dir collision.

- [ ] **Step 1: Update tests/test_agent.py to match the new signatures**

Replace the entire `tests/test_agent.py` with:

```python
from unittest.mock import MagicMock
import pytest
from agent import _build_prompt, _authenticated_url, _repo_slug


def _settings(platform="github"):
    s = MagicMock()
    s.github_token = "ghp_testtoken"
    s.gitlab_token = "glpat_testtoken"
    return s


def _repo_url(platform="github"):
    if platform == "github":
        return "https://github.com/owner/repo"
    return "https://gitlab.example.com/owner/repo"


def test_build_prompt_contains_title():
    prompt = _build_prompt("Fix the login bug", "Users cannot log in")
    assert "Fix the login bug" in prompt


def test_build_prompt_contains_body():
    prompt = _build_prompt("Fix the login bug", "Users cannot log in after update")
    assert "Users cannot log in after update" in prompt


def test_repo_slug_github():
    assert _repo_slug("https://github.com/owner/repo") == "owner-repo"


def test_repo_slug_strips_dot_git():
    assert _repo_slug("https://github.com/owner/repo.git") == "owner-repo"


def test_repo_slug_gitlab_namespace():
    assert _repo_slug("https://gitlab.example.com/group/project") == "group-project"


def test_authenticated_url_github_embeds_token():
    url = _authenticated_url(_settings("github"), _repo_url("github"), "github")
    assert "x-access-token:ghp_testtoken@github.com" in url
    assert url.startswith("https://")


def test_authenticated_url_gitlab_embeds_token():
    url = _authenticated_url(_settings("gitlab"), _repo_url("gitlab"), "gitlab")
    assert "oauth2:glpat_testtoken@gitlab.example.com" in url
    assert url.startswith("https://")


def test_authenticated_url_github_no_dot_git():
    s = MagicMock()
    s.github_token = "tok"
    s.gitlab_token = ""
    url = _authenticated_url(s, "https://github.com/owner/repo.git", "github")
    assert url.startswith("https://x-access-token:tok@github.com")


def test_run_agent_uses_provided_engine():
    from unittest.mock import MagicMock, patch
    from agent import run_agent

    mock_engine = MagicMock()
    mock_engine.run.return_value = "Engine output"

    settings = MagicMock()
    settings.test_cmd = ""
    settings.max_retries = 3

    with patch("agent._prepare_repo"), \
         patch("agent._configure_git_user"), \
         patch("agent._git_head", return_value="abc123"):
        success, _, initial, err = run_agent(
            issue_number=1,
            issue_title="Test",
            issue_body="Body",
            branch="ai/issue-1-test",
            settings=settings,
            engine=mock_engine,
            repo_url="https://github.com/owner/repo",
            platform="github",
        )

    assert success is True
    mock_engine.run.assert_called_once()


def test_push_branch_includes_force_with_lease_when_force_true():
    from unittest.mock import patch
    from agent import push_branch

    settings = MagicMock()
    settings.github_token = "tok"

    with patch("agent.subprocess.run") as mock_run:
        push_branch(
            "/repo",
            "ai/issue-1-test",
            settings,
            repo_url="https://github.com/owner/repo",
            platform="github",
            force=True,
        )

    push_cmd = mock_run.call_args_list[1][0][0]
    assert "--force-with-lease" in push_cmd


def test_push_branch_no_force_flag_by_default():
    from unittest.mock import patch
    from agent import push_branch

    settings = MagicMock()
    settings.github_token = "tok"

    with patch("agent.subprocess.run") as mock_run:
        push_branch(
            "/repo",
            "ai/issue-1-test",
            settings,
            repo_url="https://github.com/owner/repo",
            platform="github",
        )

    push_cmd = mock_run.call_args_list[1][0][0]
    assert "--force-with-lease" not in push_cmd


def test_run_agent_accepts_start_ref():
    from unittest.mock import MagicMock, patch
    from agent import run_agent

    mock_engine = MagicMock()
    mock_engine.run.return_value = "output"

    settings = MagicMock()
    settings.test_cmd = ""
    settings.max_retries = 3

    captured = {}

    def fake_prepare(repo_path, branch, settings, repo_url, platform, start_ref=""):
        captured["start_ref"] = start_ref

    with patch("agent._prepare_repo", side_effect=fake_prepare), \
         patch("agent._configure_git_user"), \
         patch("agent._git_head", return_value="abc123"):
        run_agent(
            issue_number=1,
            issue_title="Test",
            issue_body="Body",
            branch="ai/issue-1-test",
            settings=settings,
            engine=mock_engine,
            repo_url="https://github.com/owner/repo",
            platform="github",
            start_ref="origin/ai/issue-1-test",
        )

    assert captured["start_ref"] == "origin/ai/issue-1-test"
```

- [ ] **Step 2: Run to verify failures**

```bash
python -m pytest tests/test_agent.py -v 2>&1 | tail -25
```

Expected: failures on `_repo_slug` not found, wrong signatures for `_authenticated_url`, `run_agent`, `push_branch`.

- [ ] **Step 3: Update agent.py**

Replace the entire `agent.py` with:

```python
import logging
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from tempfile import gettempdir
from urllib.parse import urlparse, urlunparse

from config import Settings
from engines.base import AgentEngine

logger = logging.getLogger(__name__)

WORK_DIR = Path(gettempdir()) / "ai-coding-flow"


def cleanup_repo(repo_path: str) -> None:
    try:
        shutil.rmtree(repo_path, ignore_errors=True)
        logger.info("Cleaned up work dir: %s", repo_path)
    except Exception:
        logger.exception("Failed to clean up %s", repo_path)


def cleanup_old_repos(max_age_days: int = 2) -> None:
    """Remove any work directories older than max_age_days. Call on startup."""
    if not WORK_DIR.exists():
        return
    cutoff = time.time() - max_age_days * 86400
    for child in WORK_DIR.iterdir():
        if child.is_dir() and child.stat().st_mtime < cutoff:
            try:
                shutil.rmtree(child)
                logger.info("Evicted stale work dir: %s", child)
            except Exception:
                logger.exception("Failed to evict stale dir: %s", child)


def run_agent(
    issue_number: int,
    issue_title: str,
    issue_body: str,
    branch: str,
    settings: Settings,
    engine: AgentEngine,
    repo_url: str,
    platform: str,
    start_ref: str = "",
) -> tuple[bool, str, str, str]:
    """
    Clone repo, run engine, retry on test failure.
    Returns (success, repo_path, initial_commit, error_msg).
    Synchronous — caller must use asyncio.to_thread.
    """
    repo_path = WORK_DIR / f"{_repo_slug(repo_url)}-{issue_number}"
    _prepare_repo(repo_path, branch, settings, repo_url, platform, start_ref=start_ref)
    _configure_git_user(repo_path)
    initial_commit = _git_head(repo_path)

    prompt = _build_prompt(issue_title, issue_body)

    if not settings.test_cmd:
        logger.info("Running %s (no test cmd) for issue #%d", engine.name, issue_number)
        engine_output = engine.run(repo_path, prompt, settings)
        head_after = _git_head(repo_path)
        if head_after == initial_commit:
            logger.warning("%s made no commits for issue #%d. Output:\n%s", engine.name, issue_number, engine_output)
        return True, str(repo_path), initial_commit, ""

    error_msg = ""
    for attempt in range(settings.max_retries):
        if attempt > 0:
            prompt = (
                f"The tests are still failing after your last attempt.\n\n"
                f"Test output:\n```\n{error_msg}\n```\n\n"
                f"Please fix the code so all tests pass."
            )
        logger.info("Running %s (attempt %d/%d) for issue #%d", engine.name, attempt + 1, settings.max_retries, issue_number)
        engine.run(repo_path, prompt, settings)
        passed, error_msg = _run_tests(repo_path, settings.test_cmd)
        if passed:
            return True, str(repo_path), initial_commit, ""

    logger.warning("Agent exhausted retries for issue #%d", issue_number)
    return False, str(repo_path), initial_commit, error_msg


def push_branch(
    repo_path: str,
    branch: str,
    settings: Settings,
    repo_url: str,
    platform: str,
    force: bool = False,
) -> None:
    auth_url = _authenticated_url(settings, repo_url, platform)
    subprocess.run(
        ["git", "remote", "set-url", "origin", auth_url],
        cwd=repo_path, check=True, capture_output=True,
    )
    cmd = ["git", "push", "-u", "origin", branch]
    if force:
        cmd.append("--force-with-lease")
    subprocess.run(cmd, cwd=repo_path, check=True, capture_output=True,
                   env={**os.environ, **_git_ssl_env(settings)})


def get_diff(repo_path: str, initial_commit: str) -> str:
    result = subprocess.run(
        ["git", "diff", initial_commit, "HEAD"],
        cwd=repo_path, capture_output=True, text=True,
    )
    return result.stdout[:15000]


def _repo_slug(repo_url: str) -> str:
    path = urlparse(repo_url).path.strip("/").removesuffix(".git")
    return re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")


def _prepare_repo(
    repo_path: Path,
    branch: str,
    settings: Settings,
    repo_url: str,
    platform: str,
    start_ref: str = "",
) -> None:
    auth_url = _authenticated_url(settings, repo_url, platform)
    net_env = {**os.environ, **_git_ssl_env(settings)}
    if (repo_path / ".git").exists():
        subprocess.run(["git", "fetch", "origin"], cwd=repo_path, check=True, capture_output=True,
                       env=net_env)
        if not start_ref:
            result = subprocess.run(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=repo_path, capture_output=True, text=True,
            )
            default = result.stdout.strip().split("/")[-1] if result.returncode == 0 else "main"
            subprocess.run(["git", "checkout", default], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "reset", "--hard", f"origin/{default}"],
                cwd=repo_path, check=True, capture_output=True,
            )
    else:
        repo_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", auth_url, str(repo_path)], check=True, capture_output=True,
                       env=net_env)
        if start_ref:
            subprocess.run(["git", "fetch", "origin"], cwd=repo_path, check=True, capture_output=True,
                           env=net_env)
    checkout_cmd = ["git", "checkout", "-B", branch]
    if start_ref:
        checkout_cmd.append(start_ref)
    subprocess.run(checkout_cmd, cwd=repo_path, check=True, capture_output=True)


def _configure_git_user(repo_path: Path) -> None:
    subprocess.run(
        ["git", "config", "user.email", "ai-coding-flow@localhost"],
        cwd=repo_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "AI Coding Flow"],
        cwd=repo_path, check=True, capture_output=True,
    )


def _git_head(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _build_prompt(title: str, body: str) -> str:
    return (
        f"Resolve the following issue in this Python repository.\n\n"
        f"Issue title: {title}\n\n"
        f"Issue description:\n{body}\n\n"
        f"Instructions:\n"
        f"1. Understand what the issue requires.\n"
        f"2. Write the necessary code changes.\n"
        f"3. Write or update tests that verify the fix.\n"
        f"4. Make sure all tests pass before finishing."
    )


_PY_COMPAT_SHIM = '''\
import pathlib
import py.path
_orig_local_init = py.path.local.__init__
def _patched_local_init(self, path=None, expanduser=False):
    if isinstance(path, pathlib.Path):
        path = str(path)
    _orig_local_init(self, path=path, expanduser=expanduser)
py.path.local.__init__ = _patched_local_init
'''


def _ensure_py_compat(repo_path: Path) -> None:
    """Prepend py.path.local shim to conftest.py so pytest 8 + py 1.4 don't crash."""
    conf = repo_path / "conftest.py"
    if conf.exists():
        content = conf.read_text()
        if "py.path.local.__init__" not in content:
            conf.write_text(_PY_COMPAT_SHIM + "\n" + content)
    else:
        conf.write_text(_PY_COMPAT_SHIM)


def _run_tests(repo_path: Path, test_cmd: str) -> tuple[bool, str]:
    _ensure_py_compat(repo_path)
    result = subprocess.run(
        shlex.split(test_cmd),
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = (result.stdout + result.stderr)[-3000:]
    return result.returncode == 0, output


def _authenticated_url(settings: Settings, repo_url: str, platform: str) -> str:
    parsed = urlparse(repo_url)
    if platform == "github":
        netloc = f"x-access-token:{settings.github_token}@{parsed.netloc}"
    else:
        netloc = f"oauth2:{settings.gitlab_token}@{parsed.netloc}"
    return urlunparse(parsed._replace(netloc=netloc))


def _git_ssl_env(settings: Settings) -> dict:
    if not settings.verify_repo_ssl:
        return {"GIT_SSL_NO_VERIFY": "true"}
    return {}
```

- [ ] **Step 4: Run test_agent.py — all should pass**

```bash
python -m pytest tests/test_agent.py -v
```

Expected: all green.

- [ ] **Step 5: Confirm test_worker.py still passes (it mocks run_agent/push_branch)**

```bash
python -m pytest tests/test_worker.py -v 2>&1 | tail -20
```

Expected: all green (mocks insulate worker tests from signature changes).

- [ ] **Step 6: Commit**

```bash
git add agent.py tests/test_agent.py
git commit -m "feat: make run_agent and push_branch accept explicit repo_url and platform"
```

---

### Task 4: Update platform factory signature

**Files:**
- Modify: `platforms/__init__.py`

No dedicated test file for this module — it is tested indirectly via integration. The change is straightforward.

- [ ] **Step 1: Update platforms/__init__.py**

Replace the entire `platforms/__init__.py` with:

```python
from .base import GitPlatform, Issue
from .github import GitHubPlatform
from .gitlab import GitLabPlatform


def create_platform(platform: str, repo_url: str, settings) -> GitPlatform:
    if platform == "github":
        return GitHubPlatform(token=settings.github_token, repo_url=repo_url)
    if platform == "gitlab":
        return GitLabPlatform(token=settings.gitlab_token, repo_url=repo_url)
    raise ValueError(f"Unknown platform: {platform}")
```

- [ ] **Step 2: Run full suite to verify nothing regressed**

```bash
python -m pytest --tb=short 2>&1 | tail -20
```

Expected: same pass count as before (worker tests mock `create_platform`; no test calls it directly).

- [ ] **Step 3: Commit**

```bash
git add platforms/__init__.py
git commit -m "feat: create_platform takes explicit platform and repo_url instead of settings"
```

---

### Task 5: Thread repo_url through worker pipeline

**Files:**
- Modify: `worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Add repo_url to Job and update test_worker.py**

Replace the entire `tests/test_worker.py` with:

```python
import pytest
from unittest.mock import MagicMock
from worker import _slugify


def test_slugify_basic():
    assert _slugify("Fix the login bug") == "fix-the-login-bug"


def test_slugify_special_characters():
    assert _slugify("Support UTF-8 & unicode!") == "support-utf-8-unicode"


def test_slugify_truncates_at_50():
    result = _slugify("word " * 20)
    assert len(result) <= 50


def test_slugify_trims_leading_trailing_hyphens():
    result = _slugify("  Fix bug  ")
    assert not result.startswith("-")
    assert not result.endswith("-")


def test_pick_engine_selects_aider_by_label():
    from worker import _pick_engine
    from engines.aider import AiderEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["ai: processing", "agent: aider", "bug"], settings)
    assert isinstance(engine, AiderEngine)


def test_pick_engine_selects_opencode_by_label():
    from worker import _pick_engine
    from engines.opencode import OpenCodeEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["agent: opencode"], settings)
    assert isinstance(engine, OpenCodeEngine)


def test_pick_engine_uses_default_when_no_agent_label():
    from worker import _pick_engine
    from engines.aider import AiderEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["bug", "ai: done"], settings)
    assert isinstance(engine, AiderEngine)


def test_pick_engine_unknown_label_falls_back_to_opencode():
    from worker import _pick_engine
    from engines.opencode import OpenCodeEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["agent: nonexistent"], settings)
    assert isinstance(engine, OpenCodeEngine)


def test_build_rework_body_contains_original_and_feedback():
    from worker import _build_rework_body
    result = _build_rework_body("Original issue body", "/rework please add error handling")
    assert "Original issue body" in result
    assert "please add error handling" in result
    assert "Reviewer feedback" in result


def test_build_rework_body_separator_present():
    from worker import _build_rework_body
    result = _build_rework_body("Body", "/rework fix it")
    assert "---" in result


import asyncio
from unittest.mock import AsyncMock, patch


def test_process_rework_job_posts_completion_comment():
    from worker import Job, _process_rework_job

    job = Job(
        platform="github",
        repo_url="https://github.com/owner/repo",
        issue_number=42,
        title="Fix bug",
        body="There is a bug",
        job_id=0,
        pr_branch="ai/issue-42-fix-bug",
        rework_comment="/rework add error handling",
    )

    settings = MagicMock()
    settings.db_path = ":memory:"
    settings.max_retries = 3
    settings.test_cmd = ""
    settings.default_agent = "aider"

    mock_platform = MagicMock()
    mock_issue = MagicMock()
    mock_issue.title = "Fix bug"
    mock_issue.body = "There is a bug"
    mock_platform.get_issue.return_value = mock_issue
    mock_platform.get_labels.return_value = []

    with patch("worker.create_platform", return_value=mock_platform), \
         patch("worker.store.update_job"), \
         patch("worker.run_agent", return_value=(True, "/tmp/repo", "abc", "")), \
         patch("worker.push_branch"):
        asyncio.run(_process_rework_job(job, settings))

    mock_platform.post_comment.assert_called_once()
    comment_text = mock_platform.post_comment.call_args[0][1]
    assert "updated" in comment_text.lower()


def test_process_rework_job_posts_failure_comment_on_error():
    from worker import Job, _process_rework_job

    job = Job(
        platform="github",
        repo_url="https://github.com/owner/repo",
        issue_number=42,
        title="Fix bug",
        body="Body",
        job_id=0,
        pr_branch="ai/issue-42-fix-bug",
        rework_comment="/rework fix it",
    )

    settings = MagicMock()
    settings.db_path = ":memory:"
    settings.max_retries = 3
    settings.test_cmd = ""
    settings.default_agent = "aider"

    mock_platform = MagicMock()
    mock_issue = MagicMock()
    mock_issue.title = "Fix bug"
    mock_issue.body = "Body"
    mock_platform.get_issue.return_value = mock_issue
    mock_platform.get_labels.return_value = []

    with patch("worker.create_platform", return_value=mock_platform), \
         patch("worker.store.update_job"), \
         patch("worker.run_agent", return_value=(False, "/tmp/repo", "abc", "tests failed")):
        asyncio.run(_process_rework_job(job, settings))

    mock_platform.post_comment.assert_called_once()
    comment_text = mock_platform.post_comment.call_args[0][1]
    assert "tests failed" in comment_text
```

- [ ] **Step 2: Run test_worker.py — expect failures on Job missing repo_url**

```bash
python -m pytest tests/test_worker.py -v 2>&1 | tail -20
```

Expected: `TypeError` on `Job(...)` missing `repo_url`.

- [ ] **Step 3: Update worker.py**

Replace the entire `worker.py` with:

```python
import asyncio
import logging
import re
from dataclasses import dataclass

import store
from config import Settings
from agent import run_agent, push_branch, get_diff, cleanup_repo, cleanup_old_repos
from reviewer import run_review
from platforms import create_platform
from engines import get_engine
from engines.base import AgentEngine

logger = logging.getLogger(__name__)

_settings_ref: Settings | None = None


@dataclass
class Job:
    platform: str
    repo_url: str
    issue_number: int
    title: str
    body: str
    job_id: int = 0
    pr_branch: str = ""
    rework_comment: str = ""


_queue: asyncio.Queue = asyncio.Queue()


async def enqueue_job(
    *,
    platform: str,
    repo_url: str,
    issue_number: int,
    title: str,
    body: str,
    pr_branch: str = "",
    rework_comment: str = "",
) -> None:
    job_id = 0
    if _settings_ref:
        job_id = store.create_job(
            _settings_ref.db_path,
            platform=platform,
            repo_url=repo_url,
            issue_number=issue_number,
            issue_title=title,
        )
    await _queue.put(Job(
        platform=platform,
        repo_url=repo_url,
        issue_number=issue_number,
        title=title,
        body=body,
        job_id=job_id,
        pr_branch=pr_branch,
        rework_comment=rework_comment,
    ))
    logger.info("Enqueued issue #%d (%s) from %s", issue_number, platform, repo_url)


async def start_worker(settings: Settings) -> None:
    global _settings_ref
    _settings_ref = settings
    cleanup_old_repos()
    logger.info("Worker started")
    while True:
        job = await _queue.get()
        try:
            if job.rework_comment and job.pr_branch:
                await _process_rework_job(job, settings)
            else:
                await _process_job(job, settings)
        except Exception as exc:
            logger.exception("Unhandled error for issue #%d", job.issue_number)
            try:
                platform = create_platform(job.platform, job.repo_url, settings)
                platform.remove_label(job.issue_number, _LABEL_PROCESSING)
                platform.set_label(job.issue_number, _LABEL_FAILED)
                platform.post_comment(
                    job.issue_number,
                    f"AI workflow encountered an unexpected error: {exc}",
                )
            except Exception:
                logger.exception("Failed to post error comment for issue #%d", job.issue_number)
        finally:
            _queue.task_done()


_LABEL_PROCESSING = "ai: processing"
_LABEL_DONE = "ai: done"
_LABEL_FAILED = "ai: failed"
_LABEL_NEEDS_CLARIFICATION = "ai: needs clarification"

_ALL_AI_LABELS = (
    _LABEL_PROCESSING,
    _LABEL_DONE,
    _LABEL_FAILED,
    _LABEL_NEEDS_CLARIFICATION,
)


def _swap_label(platform, issue_number: int, remove: str, add: str) -> None:
    for label in _ALL_AI_LABELS:
        if label == add:
            continue
        try:
            platform.remove_label(issue_number, label)
        except Exception:
            pass
    try:
        platform.set_label(issue_number, add)
    except Exception:
        logger.exception("Failed to set label %r on issue #%d", add, issue_number)


def _pick_engine(labels: list[str], settings: Settings) -> AgentEngine:
    for label in labels:
        if label.startswith("agent: "):
            engine_name = label[len("agent: "):]
            return get_engine(engine_name)
    return get_engine(settings.default_agent)


def _build_rework_body(original_body: str, rework_comment: str) -> str:
    return (
        f"{original_body}\n\n"
        f"---\n"
        f"**Reviewer feedback (please address):**\n\n"
        f"{rework_comment}"
    )


async def _process_job(job: Job, settings: Settings) -> None:
    platform = create_platform(job.platform, job.repo_url, settings)
    branch = f"ai/issue-{job.issue_number}-{_slugify(job.title)}"
    logger.info("Processing issue #%d on branch %s", job.issue_number, branch)

    labels = platform.get_labels(job.issue_number)
    engine = _pick_engine(labels, settings)
    logger.info("Using engine %r for issue #%d", engine.name, job.issue_number)

    _swap_label(platform, job.issue_number, "", _LABEL_PROCESSING)
    if job.job_id:
        store.update_job(settings.db_path, job.job_id, status="processing", engine=engine.name)

    issue_body = _build_rework_body(job.body, job.rework_comment) if job.rework_comment else job.body
    success, repo_path, initial_commit, error_msg = await asyncio.to_thread(
        run_agent,
        issue_number=job.issue_number,
        issue_title=job.title,
        issue_body=issue_body,
        branch=branch,
        settings=settings,
        engine=engine,
        repo_url=job.repo_url,
        platform=job.platform,
    )

    try:
        if not success:
            _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_FAILED)
            if job.job_id:
                store.update_job(settings.db_path, job.job_id, status="failed", error_msg=error_msg)
            platform.post_comment(
                job.issue_number,
                f"AI could not produce passing tests after {settings.max_retries} attempts.\n\n"
                f"Last test output:\n```\n{error_msg}\n```",
            )
            return

        diff = get_diff(repo_path, initial_commit)
        if not diff.strip():
            _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_NEEDS_CLARIFICATION)
            if job.job_id:
                store.update_job(settings.db_path, job.job_id, status="needs_clarification")
            platform.post_comment(
                job.issue_number,
                "AI made no code changes. Please add more detail or a concrete example to the issue description.",
            )
            return

        await asyncio.to_thread(
            push_branch,
            repo_path,
            branch,
            settings,
            job.repo_url,
            job.platform,
            force=True,
        )

        pr_title = f"fix: {job.title} (resolves #{job.issue_number})"
        pr_body = (
            f"Closes #{job.issue_number}\n\n"
            f"This PR was automatically generated by the AI coding workflow."
        )
        pr_url = platform.create_pr(branch, pr_title, pr_body)
        logger.info("Created PR/MR: %s", pr_url)
        if job.job_id:
            store.update_job(settings.db_path, job.job_id, pr_url=pr_url)

        review_comment = await asyncio.to_thread(
            run_review,
            issue_title=job.title,
            issue_body=job.body,
            diff=diff,
            settings=settings,
        )

        _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_DONE)
        if job.job_id:
            store.update_job(settings.db_path, job.job_id, status="done")
        platform.post_comment(
            job.issue_number,
            f"PR: {pr_url}\n\n**Review:**\n\n{review_comment}",
        )
        logger.info("Posted review comment for issue #%d", job.issue_number)
    finally:
        cleanup_repo(repo_path)


async def _process_rework_job(job: Job, settings: Settings) -> None:
    platform = create_platform(job.platform, job.repo_url, settings)
    if job.job_id:
        store.update_job(settings.db_path, job.job_id, status="reworking")
    _swap_label(platform, job.issue_number, "", _LABEL_PROCESSING)
    logger.info("Processing rework for issue #%d on branch %s", job.issue_number, job.pr_branch)

    issue = platform.get_issue(job.issue_number)
    labels = platform.get_labels(job.issue_number)
    engine = _pick_engine(labels, settings)
    logger.info("Using engine %r for rework of issue #%d", engine.name, job.issue_number)

    if not job.pr_branch:
        logger.error("Rework job for issue #%d has empty pr_branch — skipping", job.issue_number)
        platform.post_comment(job.issue_number, "Rework skipped: could not determine branch name.")
        _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_FAILED)
        return

    success, repo_path_str, _initial_commit, error_msg = await asyncio.to_thread(
        run_agent,
        issue_number=job.issue_number,
        issue_title=issue.title,
        issue_body=_build_rework_body(issue.body, job.rework_comment),
        branch=job.pr_branch,
        settings=settings,
        engine=engine,
        repo_url=job.repo_url,
        platform=job.platform,
        start_ref=f"origin/{job.pr_branch}",
    )

    try:
        if not success:
            _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_FAILED)
            if job.job_id:
                store.update_job(settings.db_path, job.job_id, status="failed", error_msg=error_msg)
            platform.post_comment(
                job.issue_number,
                f"Re-run could not produce passing tests.\n\n```\n{error_msg}\n```",
            )
            return

        await asyncio.to_thread(
            push_branch,
            repo_path_str,
            job.pr_branch,
            settings,
            job.repo_url,
            job.platform,
            force=True,
        )
        _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_DONE)
        if job.job_id:
            store.update_job(settings.db_path, job.job_id, status="done")
        platform.post_comment(
            job.issue_number,
            f"Re-run complete. Branch `{job.pr_branch}` updated.",
        )
        logger.info("Rework complete for issue #%d", job.issue_number)
    finally:
        cleanup_repo(repo_path_str)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:50]
```

- [ ] **Step 4: Run test_worker.py — all should pass**

```bash
python -m pytest tests/test_worker.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: add repo_url to Job and thread it through worker pipeline"
```

---

### Task 6: Extract repo_url from webhook payloads in server.py

**Files:**
- Modify: `server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Update tests/test_server.py**

Replace the entire `tests/test_server.py` with:

```python
import hashlib
import hmac
import json
import os
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


SECRET = "test-secret"
GITHUB_REPO_URL = "https://github.com/owner/repo.git"
GITLAB_REPO_URL = "https://gitlab.example.com/owner/repo.git"


def _sign(body: bytes, secret: str = SECRET) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


ISSUE_OPENED = {
    "action": "opened",
    "repository": {"clone_url": GITHUB_REPO_URL},
    "issue": {"number": 42, "title": "Fix bug", "body": "There is a bug"},
}

GITLAB_ISSUE_OPENED = {
    "object_kind": "issue",
    "project": {"http_url_to_repo": GITLAB_REPO_URL},
    "object_attributes": {
        "iid": 7,
        "title": "Fix bug",
        "description": "There is a bug",
        "action": "open",
    },
}


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")


@pytest.fixture
def client():
    import importlib
    import server
    importlib.reload(server)
    return TestClient(server.app, raise_server_exceptions=True)


def test_github_valid_signature_queues_job(client):
    body = json.dumps(ISSUE_OPENED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["repo_url"] == GITHUB_REPO_URL
    assert kwargs["platform"] == "github"


def test_github_invalid_signature_returns_403(client):
    body = json.dumps(ISSUE_OPENED).encode()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=badsig", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_github_non_issue_event_is_ignored(client):
    payload = {"action": "labeled", "label": {"name": "bug"}, "repository": {"clone_url": GITHUB_REPO_URL}}
    body = json.dumps(payload).encode()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_github_issue_not_opened_is_ignored(client):
    payload = {**ISSUE_OPENED, "action": "closed"}
    body = json.dumps(payload).encode()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_gitlab_valid_token_queues_job(client):
    body = json.dumps(GITLAB_ISSUE_OPENED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["repo_url"] == GITLAB_REPO_URL
    assert kwargs["platform"] == "gitlab"


def test_gitlab_invalid_token_returns_403(client):
    body = json.dumps(GITLAB_ISSUE_OPENED).encode()
    resp = client.post(
        "/webhook/gitlab",
        content=body,
        headers={"X-Gitlab-Token": "wrongtoken", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_gitlab_non_issue_event_is_ignored(client):
    payload = {"object_kind": "push", "project": {"http_url_to_repo": GITLAB_REPO_URL}}
    body = json.dumps(payload).encode()
    resp = client.post(
        "/webhook/gitlab",
        content=body,
        headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


GITHUB_AGENT_LABELED = {
    "action": "labeled",
    "label": {"name": "agent: opencode"},
    "repository": {"clone_url": GITHUB_REPO_URL},
    "issue": {"number": 42, "title": "Fix bug", "body": "There is a bug"},
}

GITHUB_NON_AGENT_LABELED = {
    "action": "labeled",
    "label": {"name": "bug"},
    "repository": {"clone_url": GITHUB_REPO_URL},
    "issue": {"number": 42, "title": "Fix bug", "body": "There is a bug"},
}

GITLAB_LABEL_UPDATED = {
    "object_kind": "issue",
    "project": {"http_url_to_repo": GITLAB_REPO_URL},
    "object_attributes": {
        "iid": 7,
        "title": "Fix bug",
        "description": "There is a bug",
        "action": "update",
    },
    "changes": {
        "labels": {
            "previous": [],
            "current": [{"id": 1, "title": "agent: opencode"}],
        }
    },
}

GITLAB_NON_AGENT_LABEL_UPDATED = {
    "object_kind": "issue",
    "project": {"http_url_to_repo": GITLAB_REPO_URL},
    "object_attributes": {
        "iid": 7,
        "title": "Fix bug",
        "description": "There is a bug",
        "action": "update",
    },
    "changes": {
        "labels": {
            "previous": [],
            "current": [{"id": 2, "title": "priority: high"}],
        }
    },
}


def test_github_agent_label_added_queues_job(client):
    body = json.dumps(GITHUB_AGENT_LABELED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.kwargs["repo_url"] == GITHUB_REPO_URL


def test_github_non_agent_label_added_is_ignored(client):
    body = json.dumps(GITHUB_NON_AGENT_LABELED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    mock_enqueue.assert_not_called()


def test_gitlab_agent_label_added_queues_job(client):
    body = json.dumps(GITLAB_LABEL_UPDATED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.kwargs["repo_url"] == GITLAB_REPO_URL


def test_gitlab_non_agent_label_update_is_ignored(client):
    body = json.dumps(GITLAB_NON_AGENT_LABEL_UPDATED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    mock_enqueue.assert_not_called()


GITHUB_REWORK_COMMENT = {
    "action": "created",
    "sender": {"type": "User"},
    "repository": {"clone_url": GITHUB_REPO_URL},
    "comment": {"body": "/rework please add error handling"},
    "issue": {
        "number": 42,
        "title": "Fix bug",
        "body": "There is a bug",
        "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/10"},
    },
}

GITHUB_BOT_REWORK_COMMENT = {
    "action": "created",
    "sender": {"type": "Bot"},
    "repository": {"clone_url": GITHUB_REPO_URL},
    "comment": {"body": "/rework please add error handling"},
    "issue": {
        "number": 42,
        "title": "Fix bug",
        "body": "There is a bug",
        "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/10"},
    },
}

GITLAB_REWORK_NOTE = {
    "object_kind": "note",
    "project": {"http_url_to_repo": GITLAB_REPO_URL},
    "object_attributes": {
        "noteable_type": "MergeRequest",
        "note": "/rework please add error handling",
    },
    "merge_request": {
        "title": "fix: Fix bug",
        "description": "There is a bug",
        "source_branch": "ai/issue-42-fix-bug",
    },
}


def test_github_rework_comment_queues_rework_job(client):
    body = json.dumps(GITHUB_REWORK_COMMENT).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue, \
         patch("server._get_github_pr_branch", return_value="ai/issue-42-fix-bug"):
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["pr_branch"] == "ai/issue-42-fix-bug"
    assert "/rework" in kwargs["rework_comment"]
    assert kwargs["repo_url"] == GITHUB_REPO_URL


def test_github_rework_on_plain_issue_queues_fresh_job(client):
    payload = {
        "action": "created",
        "sender": {"type": "User"},
        "repository": {"clone_url": GITHUB_REPO_URL},
        "comment": {"body": "/rework try again"},
        "issue": {
            "number": 5,
            "title": "Fix bug",
            "body": "There is a bug",
        },
    }
    body = json.dumps(payload).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["issue_number"] == 5
    assert "pr_branch" not in kwargs
    assert kwargs["repo_url"] == GITHUB_REPO_URL


def test_github_bot_rework_comment_is_ignored(client):
    body = json.dumps(GITHUB_BOT_REWORK_COMMENT).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    mock_enqueue.assert_not_called()


def test_gitlab_rework_note_queues_rework_job(client):
    body = json.dumps(GITLAB_REWORK_NOTE).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["pr_branch"] == "ai/issue-42-fix-bug"
    assert "/rework" in kwargs["rework_comment"]
    assert kwargs["repo_url"] == GITLAB_REPO_URL


def test_gitlab_rework_on_plain_issue_queues_fresh_job(client):
    payload = {
        "object_kind": "note",
        "project": {"http_url_to_repo": GITLAB_REPO_URL},
        "object_attributes": {
            "noteable_type": "Issue",
            "noteable_id": 7,
            "note": "/rework try again",
        },
        "issue": {
            "iid": 7,
            "title": "Fix bug",
            "description": "There is a bug",
        },
    }
    body = json.dumps(payload).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["issue_number"] == 7
    assert "pr_branch" not in kwargs
    assert kwargs["repo_url"] == GITLAB_REPO_URL


def test_api_jobs_open_when_no_password(client):
    with patch("server.store.list_jobs", return_value=[]):
        resp = client.get("/api/jobs")
    assert resp.status_code == 200


def test_api_jobs_wrong_token_returns_401(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret123")
    import importlib
    import server
    importlib.reload(server)
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    with patch("server.store.list_jobs", return_value=[]):
        resp = c.get("/api/jobs", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


def test_api_jobs_correct_token_returns_200(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret123")
    import importlib
    import server
    importlib.reload(server)
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    with patch("server.store.list_jobs", return_value=[{"id": 1, "status": "done"}]):
        resp = c.get("/api/jobs", headers={"X-Admin-Token": "secret123"})
    assert resp.status_code == 200
    assert resp.json()[0]["status"] == "done"
```

- [ ] **Step 2: Run test_server.py — expect failures**

```bash
python -m pytest tests/test_server.py -v 2>&1 | tail -30
```

Expected: failures because `enqueue_job` is not yet called with `repo_url`/`platform`, and `PLATFORM`/`REPO_URL` removal causes Settings reload issues.

- [ ] **Step 3: Update server.py**

Replace the entire `server.py` with:

```python
import asyncio
import hashlib
import hmac
import json
import logging
import re
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

import store
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import Settings
from worker import enqueue_job, start_worker

logger = logging.getLogger(__name__)
settings = Settings()
logging.basicConfig(level=logging.DEBUG if settings.verbose else logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db(settings.db_path)
    task = asyncio.create_task(start_worker(settings))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


_DOCS_DIR = Path(__file__).parent / "docs_site"

app = FastAPI(lifespan=lifespan)
app.mount("/guide", StaticFiles(directory=str(_DOCS_DIR), html=True), name="docs")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return RedirectResponse(url="/guide")


@app.get("/api/jobs")
async def api_jobs(request: Request):
    if settings.admin_password:
        token = request.headers.get("X-Admin-Token", "")
        if not hmac.compare_digest(token, settings.admin_password):
            raise HTTPException(status_code=401, detail="Unauthorized")
    return store.list_jobs(settings.db_path)


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    _verify_github_signature(body, signature, settings.webhook_secret)

    payload = await request.json()
    action = payload.get("action")
    repo_url = payload.get("repository", {}).get("clone_url", "")

    if action == "opened" and "issue" in payload:
        issue = payload["issue"]
        background_tasks.add_task(
            enqueue_job,
            platform="github",
            repo_url=repo_url,
            issue_number=issue["number"],
            title=issue.get("title", ""),
            body=issue.get("body") or "",
        )
        return {"status": "queued"}

    if action == "labeled" and "issue" in payload:
        label_name = payload.get("label", {}).get("name", "")
        if label_name.startswith("agent: "):
            issue = payload["issue"]
            background_tasks.add_task(
                enqueue_job,
                platform="github",
                repo_url=repo_url,
                issue_number=issue["number"],
                title=issue.get("title", ""),
                body=issue.get("body") or "",
            )
            return {"status": "queued"}

    if action == "created" and "comment" in payload and "issue" in payload:
        issue = payload["issue"]
        comment_body = payload["comment"].get("body", "")
        if "/rework" in comment_body and payload.get("sender", {}).get("type", "") != "Bot":
            if issue.get("pull_request"):
                pr_api_url = issue["pull_request"].get("url", "")
                try:
                    branch = await asyncio.to_thread(_get_github_pr_branch, pr_api_url, settings.github_token)
                except Exception:
                    logger.warning("Could not fetch PR branch from %s", pr_api_url)
                    return {"status": "ignored"}
                issue_number = _parse_issue_number_from_branch(branch)
                if not issue_number:
                    logger.warning("Could not parse issue number from branch %r", branch)
                    return {"status": "ignored"}
                background_tasks.add_task(
                    enqueue_job,
                    platform="github",
                    repo_url=repo_url,
                    issue_number=issue_number,
                    title=issue.get("title", ""),
                    body=issue.get("body") or "",
                    pr_branch=branch,
                    rework_comment=comment_body,
                )
            else:
                background_tasks.add_task(
                    enqueue_job,
                    platform="github",
                    repo_url=repo_url,
                    issue_number=issue["number"],
                    title=issue.get("title", ""),
                    body=issue.get("body") or "",
                    rework_comment=comment_body,
                )
            return {"status": "queued"}

    return {"status": "ignored"}


@app.post("/webhook/gitlab")
async def gitlab_webhook(request: Request, background_tasks: BackgroundTasks):
    token = request.headers.get("X-Gitlab-Token", "")
    if not hmac.compare_digest(token, settings.webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid token")

    payload = await request.json()
    attrs = payload.get("object_attributes", {})
    repo_url = payload.get("project", {}).get("http_url_to_repo", "")

    if payload.get("object_kind") == "issue" and attrs.get("action") == "open":
        background_tasks.add_task(
            enqueue_job,
            platform="gitlab",
            repo_url=repo_url,
            issue_number=attrs["iid"],
            title=attrs.get("title", ""),
            body=attrs.get("description") or "",
        )
        return {"status": "queued"}

    if payload.get("object_kind") == "issue" and attrs.get("action") == "update":
        label_changes = payload.get("changes", {}).get("labels", {})
        previous = {l.get("title", "") for l in label_changes.get("previous", [])}
        current = {l.get("title", "") for l in label_changes.get("current", [])}
        newly_added = current - previous
        if any(lbl.startswith("agent: ") for lbl in newly_added):
            background_tasks.add_task(
                enqueue_job,
                platform="gitlab",
                repo_url=repo_url,
                issue_number=attrs["iid"],
                title=attrs.get("title", ""),
                body=attrs.get("description") or "",
            )
            return {"status": "queued"}

    if payload.get("object_kind") == "note":
        note_attrs = payload.get("object_attributes", {})
        note_text = note_attrs.get("note", "")
        if "/rework" in note_text:
            if note_attrs.get("noteable_type") == "MergeRequest":
                mr = payload.get("merge_request", {})
                branch = mr.get("source_branch", "")
                issue_number = _parse_issue_number_from_branch(branch)
                if not issue_number:
                    logger.warning("Could not parse issue number from branch %r", branch)
                    return {"status": "ignored"}
                background_tasks.add_task(
                    enqueue_job,
                    platform="gitlab",
                    repo_url=repo_url,
                    issue_number=issue_number,
                    title=mr.get("title", ""),
                    body=mr.get("description") or "",
                    pr_branch=branch,
                    rework_comment=note_text,
                )
                return {"status": "queued"}
            elif note_attrs.get("noteable_type") == "Issue":
                issue = payload.get("issue", {})
                issue_number = issue.get("iid") or note_attrs.get("noteable_id")
                if not issue_number:
                    logger.warning("Could not determine issue number from GitLab note payload")
                    return {"status": "ignored"}
                background_tasks.add_task(
                    enqueue_job,
                    platform="gitlab",
                    repo_url=repo_url,
                    issue_number=issue_number,
                    title=issue.get("title", ""),
                    body=issue.get("description") or "",
                    rework_comment=note_text,
                )
                return {"status": "queued"}

    return {"status": "ignored"}


def _verify_github_signature(body: bytes, signature: str, secret: str) -> None:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")


def _parse_issue_number_from_branch(branch: str) -> int | None:
    m = re.search(r"ai/issue-(\d+)-", branch)
    return int(m.group(1)) if m else None


def _get_github_pr_branch(pr_api_url: str, token: str) -> str:
    req = urllib.request.Request(
        pr_api_url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data.get("head", {}).get("ref", "")
```

- [ ] **Step 4: Run test_server.py — all should pass**

```bash
python -m pytest tests/test_server.py -v
```

Expected: all green.

- [ ] **Step 5: Run the full test suite**

```bash
python -m pytest --tb=short 2>&1 | tail -30
```

Expected: all green across all test files.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: extract repo_url and platform from webhook payloads"
```

---

### Task 7: Clean up .env.example

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Remove PLATFORM and REPO_URL from .env.example**

Edit `.env.example`: delete the two lines `PLATFORM=github` and `REPO_URL=https://github.com/t-community/demo-repository`.

The `# ── Platform ──` section should read:

```ini
# ── Platform ──────────────────────────────────────────────────────────────────
GITHUB_TOKEN=ghp_...
GITLAB_TOKEN=
WEBHOOK_SECRET=your-webhook-secret
# true = log all workflow steps in detail
VERBOSE=true
# false = skip SSL verification when cloning repos (self-signed certs)
VERIFY_REPO_SSL=false
# false = skip SSL verification when connecting to LLM endpoint (self-signed certs)
VERIFY_ENGINE_SSL=false
```

- [ ] **Step 2: Run the full test suite one final time**

```bash
python -m pytest --tb=short -q
```

Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "chore: remove PLATFORM and REPO_URL from .env.example"
```
