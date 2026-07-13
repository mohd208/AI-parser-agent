from pathlib import Path

from .models import JiraTicket
from .templating import write_rendered

_FILES = ["backend", "variables", "main", "outputs"]


def generate(repo_path: Path, ticket: JiraTicket) -> list[str]:
    # No AWS-specific values (account id, cluster name, OIDC provider ARN,
    # state bucket/lock table) are baked in here - they're supplied at
    # workflow-run time via `terraform init -backend-config=...` and
    # TF_VAR_* environment variables sourced from this repo's GitHub
    # Environment variables (see pipeline.py's push_environment_variables
    # and templates/github-workflows/infra-terraform.yml.j2).
    ctx = dict(
        app_name=ticket.application_name.lower().replace(" ", "-"),
        environment=ticket.environment,
    )

    written = []
    for name in _FILES:
        dest = repo_path / "terraform" / f"{name}.tf"
        write_rendered(f"terraform/app/{name}.tf.j2", dest, **ctx)
        written.append(str(dest.relative_to(repo_path)))
    return written
