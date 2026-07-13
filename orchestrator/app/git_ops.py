import shutil
import subprocess
from pathlib import Path

from .config import settings


def _run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def clone_repo(github_url: str, repo_name: str, github_token: str, tracking_id: str) -> Path:
    """Clone the repo (authenticated via token so we can push later) into a
    scratch dir scoped to this ticket's tracking id.
    """
    dest = settings.workdir / tracking_id / repo_name
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    auth_url = github_url.replace(
        "https://github.com/", f"https://x-access-token:{github_token}@github.com/"
    )
    subprocess.run(
        ["git", "clone", auth_url, str(dest)],
        capture_output=True, text=True, check=True,
    )
    return dest


def ensure_branch(repo_path: Path, branch_name: str, base_branch: str) -> None:
    """Checkout base branch, then create branch_name from it if it doesn't
    already exist (remote or local); otherwise just check it out.
    """
    _run(["fetch", "origin"], repo_path)
    _run(["checkout", base_branch], repo_path)
    _run(["pull", "origin", base_branch], repo_path)

    remote_branches = _run(["branch", "-r"], repo_path)
    if f"origin/{branch_name}" in remote_branches:
        _run(["checkout", "-B", branch_name, f"origin/{branch_name}"], repo_path)
    else:
        _run(["checkout", "-b", branch_name], repo_path)


def commit_all(repo_path: Path, message: str) -> bool:
    """Stage and commit everything. Returns False if there was nothing to commit."""
    _run(["add", "-A"], repo_path)
    status = _run(["status", "--porcelain"], repo_path)
    if not status:
        return False
    _run(["-c", "user.name=devops-ai-agent", "-c", "user.email=devops-ai-agent@bot",
          "commit", "-m", message], repo_path)
    return True


def push(repo_path: Path, branch_name: str) -> None:
    _run(["push", "-u", "origin", branch_name], repo_path)
