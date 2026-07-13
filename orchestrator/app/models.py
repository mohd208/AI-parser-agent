import re

from pydantic import BaseModel, field_validator

from .config import settings

GITHUB_URL_RE = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+?(\.git)?/?$")


class JiraTicket(BaseModel):
    issue_key: str
    application_name: str
    github_url: str
    environment: str
    branch_name: str
    reporter_email: str | None = None

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        if v not in settings.allowed_environments:
            raise ValueError(
                f"environment must be one of {settings.allowed_environments}, got {v!r}"
            )
        return v

    @field_validator("github_url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        if not GITHUB_URL_RE.match(v.strip()):
            raise ValueError(f"github_url does not look like a valid GitHub repo URL: {v!r}")
        return v.strip().rstrip("/")

    @field_validator("application_name", "branch_name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()

    @property
    def owner_repo(self) -> tuple[str, str]:
        path = self.github_url.removeprefix("https://github.com/").removesuffix(".git")
        owner, repo = path.split("/", 1)
        return owner, repo
