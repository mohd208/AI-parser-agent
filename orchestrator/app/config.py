from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    webhook_secret: str
    aws_region: str = "us-east-1"
    secret_name_template: str = "devops-agent/{environment}"

    github_base_branch: str = "main"
    pr_reviewers: str = ""  # comma-separated GitHub usernames, optional

    claude_cli_path: str = "claude"
    claude_permission_mode: str = "acceptEdits"
    claude_review_max_iterations: int = 2

    workdir: Path = Path("./_work")

    allowed_environments: tuple[str, ...] = ("dev", "staging", "prod")

    @property
    def reviewer_list(self) -> list[str]:
        return [r.strip() for r in self.pr_reviewers.split(",") if r.strip()]


settings = Settings()
settings.workdir.mkdir(parents=True, exist_ok=True)
