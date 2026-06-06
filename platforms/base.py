from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Issue:
    number: int
    title: str
    body: str
    url: str


class GitPlatform(ABC):
    @abstractmethod
    def get_issue(self, number: int) -> Issue: ...

    @abstractmethod
    def create_pr(self, branch: str, title: str, body: str) -> str:
        """Create a PR (GitHub) or MR (GitLab). Returns the PR/MR URL."""
        ...

    @abstractmethod
    def post_comment(self, issue_number: int, body: str) -> None: ...
