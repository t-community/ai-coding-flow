from pathlib import Path
from typing import Literal
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    platform: Literal["github", "gitlab"]
    repo_url: str
    github_token: str = ""
    gitlab_token: str = ""
    webhook_secret: str
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
    test_cmd: str = ""  # empty = skip testing entirely
    aider_verbose: bool = False  # set true to log all Aider output
    default_agent: str = "aider"
    admin_password: str = ""
    db_path: str = str(Path(__file__).parent / "ai_jobs.db")

    model_config = {"env_file": ".env"}
