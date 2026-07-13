from pathlib import Path

from .models import JiraTicket
from .templating import write_rendered

_WORKFLOWS = ["infra-terraform", "deploy"]


def generate(repo_path: Path, ticket: JiraTicket) -> list[str]:
    # No AWS values baked in - the workflows read vars.AWS_REGION,
    # vars.EKS_CLUSTER_NAME, etc. from this repo's GitHub Environment
    # variables at run time (see pipeline.py's push_environment_variables).
    app = ticket.application_name.lower().replace(" ", "-")
    ctx = dict(
        app_name=app,
        environment=ticket.environment,
        base_branch=ticket.branch_name,
    )

    written = []
    for name in _WORKFLOWS:
        dest = repo_path / ".github" / "workflows" / f"{name}-{app}-{ticket.environment}.yml"
        write_rendered(f"github-workflows/{name}.yml.j2", dest, **ctx)
        written.append(str(dest.relative_to(repo_path)))
    return written
