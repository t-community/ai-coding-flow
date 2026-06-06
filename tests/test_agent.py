from unittest.mock import MagicMock
import pytest
from agent import _build_prompt, _authenticated_url


def _settings(platform="github"):
    s = MagicMock()
    s.platform = platform
    s.github_token = "ghp_testtoken"
    s.gitlab_token = "glpat_testtoken"
    s.repo_url = (
        "https://github.com/owner/repo"
        if platform == "github"
        else "https://gitlab.example.com/owner/repo"
    )
    return s


def test_build_prompt_contains_title():
    prompt = _build_prompt("Fix the login bug", "Users cannot log in")
    assert "Fix the login bug" in prompt


def test_build_prompt_contains_body():
    prompt = _build_prompt("Fix the login bug", "Users cannot log in after update")
    assert "Users cannot log in after update" in prompt


def test_authenticated_url_github_embeds_token():
    url = _authenticated_url(_settings("github"))
    assert "x-access-token:ghp_testtoken@github.com" in url
    assert url.startswith("https://")


def test_authenticated_url_gitlab_embeds_token():
    url = _authenticated_url(_settings("gitlab"))
    assert "oauth2:glpat_testtoken@gitlab.example.com" in url
    assert url.startswith("https://")


def test_authenticated_url_github_no_dot_git():
    s = MagicMock()
    s.platform = "github"
    s.github_token = "tok"
    s.repo_url = "https://github.com/owner/repo.git"
    url = _authenticated_url(s)
    assert url.startswith("https://x-access-token:tok@github.com")
