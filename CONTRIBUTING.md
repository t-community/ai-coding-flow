# Contributing

## Setup

```bash
git clone https://github.com/t-community/ai-coding-flow.git
cd ai-coding-flow
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Running tests

```bash
pytest tests/ -v
```

All 36 tests run offline — no tokens, LLM, or network access needed.

## Making changes

- Keep each module focused: `server.py` handles HTTP, `agent.py` handles git/Aider, `worker.py` orchestrates
- Add or update tests for anything you change
- Run `ruff check .` before pushing

## Adding a new platform

1. Create `platforms/<name>.py` implementing `GitPlatform` from `platforms/base.py`
2. Register it in `platforms/__init__.py`'s `create_platform` factory
3. Add a webhook endpoint in `server.py`
4. Add tests in `tests/test_platforms/`

## Commit style

```
feat: short description     # new feature
fix: short description      # bug fix
chore: short description    # tooling, deps, config
docs: short description     # documentation only
```
