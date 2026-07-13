from pathlib import Path

from .language_detect import DetectedRuntime
from .templating import TEMPLATES_DIR, write_rendered


def generate(repo_path: Path, runtime: DetectedRuntime) -> bool:
    """Render a Dockerfile from the language-specific template. Skipped (returns
    False) if the repo already ships one — we don't clobber an existing,
    presumably-intentional Dockerfile.
    """
    dest = repo_path / "Dockerfile"
    if dest.exists():
        return False

    template_name = f"{runtime.language}.Dockerfile.j2"
    if not (TEMPLATES_DIR / "dockerfiles" / template_name).exists():
        template_name = "generic.Dockerfile.j2"

    # `npm ci` requires package-lock.json to exist at all - fails outright on
    # a repo that doesn't have one (common for small/new Node projects).
    # node.Dockerfile.j2 falls back to `npm install` when this is False.
    has_lockfile = (repo_path / "package-lock.json").exists() or (repo_path / "npm-shrinkwrap.json").exists()

    write_rendered(f"dockerfiles/{template_name}", dest, runtime=runtime, has_lockfile=has_lockfile)
    return True
