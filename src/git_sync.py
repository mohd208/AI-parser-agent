import re
import shutil
import subprocess
from pathlib import Path

from job_store import append_log

WORKSPACES_ROOT = Path.cwd() / "workspaces"

# name comes from the trigger payload and becomes a directory name — reject
# anything but a safe slug to avoid path traversal (e.g. "../../etc").
SAFE_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


def repo_dir_for(name):
    if not SAFE_NAME.match(name):
        raise ValueError(f'Unsafe project name "{name}": only letters, numbers, "-", "_" allowed')
    return WORKSPACES_ROOT / name


def _git(*args, cwd, job_id):
    append_log(job_id, f"$ git {' '.join(args)}")
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    for line in (proc.stdout + proc.stderr).strip().splitlines():
        append_log(job_id, line)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")


def sync_repo(repo_url, name, branch, job_id):
    WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)
    repo_dir = repo_dir_for(name)

    if (repo_dir / ".git").exists():
        append_log(job_id, f"Existing checkout found at {repo_dir}, updating in place")
        _git("fetch", "origin", branch, cwd=repo_dir, job_id=job_id)
        _git("checkout", branch, cwd=repo_dir, job_id=job_id)
        _git("reset", "--hard", f"origin/{branch}", cwd=repo_dir, job_id=job_id)
        _git("clean", "-fd", cwd=repo_dir, job_id=job_id)
    else:
        append_log(job_id, f"No existing checkout, cloning {repo_url} into {repo_dir}")
        shutil.rmtree(repo_dir, ignore_errors=True)
        _git("clone", "--branch", branch, "--single-branch", repo_url, str(repo_dir), cwd=None, job_id=job_id)

    return repo_dir


def get_short_sha(repo_dir, job_id):
    """Used to build a deterministic image tag (`<environment>-<short_sha>`)
    that agent 1 can hand to agents 2, 3 and 4 *before* the image is actually
    pushed — so the K8s manifest (agent 3) can reference the right tag
    without having to wait for the image push (agent 2) to finish first."""
    proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git rev-parse --short HEAD failed: {proc.stderr.strip()}")
    return proc.stdout.strip()
