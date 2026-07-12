import re
import shutil
import subprocess
from pathlib import Path

WORKSPACES_ROOT = Path.cwd() / "workspaces"

# name comes from the trigger payload and becomes a directory name — reject
# anything but a safe slug to avoid path traversal (e.g. "../../etc").
SAFE_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


def repo_dir_for(name):
    if not SAFE_NAME.match(name):
        raise ValueError(f'Unsafe project name "{name}": only letters, numbers, "-", "_" allowed')
    return WORKSPACES_ROOT / name


def _git(*args, cwd):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")


def sync_repo(repo_url, name, branch):
    WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)
    repo_dir = repo_dir_for(name)

    if (repo_dir / ".git").exists():
        _git("fetch", "origin", branch, cwd=repo_dir)
        _git("checkout", branch, cwd=repo_dir)
        _git("reset", "--hard", f"origin/{branch}", cwd=repo_dir)
        _git("clean", "-fd", cwd=repo_dir)
    else:
        shutil.rmtree(repo_dir, ignore_errors=True)
        _git("clone", "--branch", branch, "--single-branch", repo_url, str(repo_dir), cwd=None)

    return repo_dir
