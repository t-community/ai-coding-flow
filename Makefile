.PHONY: install run dev test clean

AIDER_SITE := $(shell uv tool dir)/aider-chat/lib/python3.12/site-packages

install:
	uv venv --python 3.13 .venv
	uv pip install -r requirements.txt
	uv tool install --force --python 3.12 aider-chat@latest

run:
	PYTHONPATH="$(AIDER_SITE)" uv run uvicorn server:app --env-file .env --port 8000

dev:
	PYTHONPATH="$(AIDER_SITE)" uv run uvicorn server:app --env-file .env --port 8000 --reload

test:
	uv run pytest

clean:
	rm -rf .venv __pycache__ .pytest_cache
