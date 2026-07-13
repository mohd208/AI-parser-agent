import requests

from .config import settings

API = "https://api.github.com"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def create_pull_request(
    owner: str, repo: str, token: str, head_branch: str, base_branch: str,
    title: str, body: str,
) -> dict:
    resp = requests.post(
        f"{API}/repos/{owner}/{repo}/pulls",
        headers=_headers(token),
        json={"title": title, "head": head_branch, "base": base_branch, "body": body},
        timeout=30,
    )
    resp.raise_for_status()
    pr = resp.json()

    reviewers = settings.reviewer_list
    if reviewers:
        requests.post(
            f"{API}/repos/{owner}/{repo}/pulls/{pr['number']}/requested_reviewers",
            headers=_headers(token),
            json={"reviewers": reviewers},
            timeout=30,
        )
    return pr


def post_pr_comment(owner: str, repo: str, token: str, pr_number: int, body: str) -> None:
    requests.post(
        f"{API}/repos/{owner}/{repo}/issues/{pr_number}/comments",
        headers=_headers(token),
        json={"body": body},
        timeout=30,
    ).raise_for_status()


def ensure_environment(owner: str, repo: str, token: str, environment: str) -> None:
    """Creates the GitHub Environment (dev/staging/prod) if it doesn't already
    exist. PUT is idempotent - safe to call on every run."""
    requests.put(
        f"{API}/repos/{owner}/{repo}/environments/{environment}",
        headers=_headers(token), json={}, timeout=30,
    ).raise_for_status()


def upsert_environment_variable(
    owner: str, repo: str, token: str, environment: str, name: str, value: str,
) -> None:
    """Creates or updates a GitHub Actions Environment variable (the plain,
    user-editable kind under Settings -> Environments -> <env> -> Variables,
    not an encrypted secret) so the generated workflows' `vars.*` references
    resolve, and so the value can be hand-edited in GitHub without re-running
    the provisioning ticket.
    """
    base = f"{API}/repos/{owner}/{repo}/environments/{environment}/variables"
    existing = requests.get(f"{base}/{name}", headers=_headers(token), timeout=30)
    if existing.status_code == 200:
        requests.patch(
            f"{base}/{name}", headers=_headers(token),
            json={"name": name, "value": value}, timeout=30,
        ).raise_for_status()
    else:
        requests.post(
            base, headers=_headers(token),
            json={"name": name, "value": value}, timeout=30,
        ).raise_for_status()
