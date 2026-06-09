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
