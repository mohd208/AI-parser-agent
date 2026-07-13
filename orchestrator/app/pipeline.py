import logging
import uuid

from . import dockerfile_gen, git_ops, github_api, k8s_gen, pr_review, terraform_gen, workflow_gen
from .claude_engine import run_claude
from .config import settings
from .language_detect import detect
from .models import JiraTicket
from .secrets_manager import get_secret

log = logging.getLogger("pipeline")

_ENHANCE_PROMPT = """You just had a Dockerfile, Kubernetes manifests (k8s/{environment}/), Terraform
(terraform/), and GitHub Actions workflows (.github/workflows/) generated
from templates for this repo, targeting the "{environment}" environment.

Look at the actual source code in this repo and tighten up what was
generated: correct the base image version / runtime version pin if it
doesn't match what this repo actually uses, fix the exposed port if the app
listens on something else, add a build step if one is missing (e.g. `npm run
build`, `mvn package`), and fix anything else that would stop this from
actually building and running. Make the edits directly. Reply with a one
paragraph summary of what, if anything, you changed.
"""


# Repo/Environment variable names the generated Terraform + workflows read
# via `vars.*` - keep this in sync with what infra-terraform.yml.j2 /
# deploy.yml.j2 / terraform/variables.tf.j2 actually reference.
_ENV_VAR_KEYS = (
    "AWS_REGION",
    "EKS_CLUSTER_NAME",
    "EKS_OIDC_PROVIDER_ARN",
    "TF_STATE_BUCKET",
    "TF_LOCK_TABLE",
    "GITHUB_OIDC_ROLE_ARN",
)


def _push_environment_variables(owner: str, repo_name: str, token: str, ticket: JiraTicket, secret: dict) -> None:
    """Creates the GitHub Environment for this ticket's environment (dev/
    staging/prod) and seeds it with the AWS/EKS config pulled from Secrets
    Manager, as plain (non-secret) GitHub Actions Variables. These are what
    the generated workflows read at run time - and because they're ordinary
    Environment variables, you can override any of them by hand in GitHub
    (Settings -> Environments -> {environment} -> Variables) without
    re-running the ticket.
    """
    github_api.ensure_environment(owner, repo_name, token, ticket.environment)
    for key in _ENV_VAR_KEYS:
        if key not in secret:
            log.warning("secret for %s is missing key %s - workflow's vars.%s will be unset", ticket.environment, key, key)
            continue
        github_api.upsert_environment_variable(owner, repo_name, token, ticket.environment, key, str(secret[key]))


def run(ticket: JiraTicket) -> dict:
    tracking_id = str(uuid.uuid4())[:8]
    log.info("[%s] starting pipeline for %s (%s)", tracking_id, ticket.application_name, ticket.issue_key)

    secret = get_secret(ticket.environment)
    owner, repo_name = ticket.owner_repo

    _push_environment_variables(owner, repo_name, secret["GITHUB_TOKEN"], ticket, secret)

    repo_path = git_ops.clone_repo(ticket.github_url, repo_name, secret["GITHUB_TOKEN"], tracking_id)
    git_ops.ensure_branch(repo_path, ticket.branch_name, settings.github_base_branch)

    runtime = detect(repo_path)
    log.info("[%s] detected runtime: %s", tracking_id, runtime)

    dockerfile_gen.generate(repo_path, runtime)
    k8s_gen.generate(repo_path, ticket, runtime)
    terraform_gen.generate(repo_path, ticket)
    workflow_gen.generate(repo_path, ticket)

    enhance = run_claude(
        _ENHANCE_PROMPT.format(environment=ticket.environment),
        cwd=repo_path,
        allowed_tools="Read,Write,Edit,Glob,Grep",
    )

    git_ops.commit_all(
        repo_path,
        f"devops-ai-agent: provision {ticket.application_name} for {ticket.environment} "
        f"({ticket.issue_key})",
    )
    git_ops.push(repo_path, ticket.branch_name)

    resource_name = f"{ticket.application_name.lower().replace(' ', '-')}-{ticket.environment}"
    pr_body = (
        f"Automated provisioning for **{ticket.application_name}** "
        f"({ticket.environment}), triggered by [{ticket.issue_key}].\n\n"
        f"Detected runtime: `{runtime.language}` `{runtime.version}`, port `{runtime.port}`.\n\n"
        f"AWS/K8s resources are named `{resource_name}` (ECR repo, IRSA role, "
        f"K8s namespace + objects). Infra config (region, cluster, state "
        f"bucket, OIDC role, etc.) has been populated as GitHub Environment "
        f"variables under **Settings > Environments > {ticket.environment} > "
        f"Variables** - edit them there if anything needs to change; nothing "
        f"AWS-specific is hardcoded in the files below. The infra pipeline "
        f"also adopts (imports) the ECR repo / IAM role instead of failing "
        f"if they already exist.\n\n"
        f"### Claude enhance pass\n{enhance.text}\n"
    )
    pr = github_api.create_pull_request(
        owner, repo_name, secret["GITHUB_TOKEN"],
        head_branch=ticket.branch_name, base_branch=settings.github_base_branch,
        title=f"[{ticket.issue_key}] Provision {ticket.application_name} ({ticket.environment})",
        body=pr_body,
    )

    review_summary = pr_review.run(repo_path, settings.github_base_branch, ticket.branch_name)
    github_api.post_pr_comment(
        owner, repo_name, secret["GITHUB_TOKEN"], pr["number"],
        f"**devops-ai-agent review**\n\n{review_summary}",
    )

    log.info("[%s] done: %s", tracking_id, pr["html_url"])
    return {"tracking_id": tracking_id, "pr_url": pr["html_url"]}
