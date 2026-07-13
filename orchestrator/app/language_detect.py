import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DetectedRuntime:
    language: str          # key into templates/dockerfiles/<language>.Dockerfile.j2
    version: str            # best-guess runtime version to pin in the base image
    port: int                # best-guess container port
    start_hint: str = ""     # human-readable note passed to Claude's review pass


_DEFAULT_PORT = {
    "node": 3000, "python": 8000, "java": 8080,
    "go": 8080, "dotnet": 8080, "ruby": 3000, "php": 8080,
}


def detect(repo_path: Path) -> DetectedRuntime:
    if (repo_path / "package.json").exists():
        return _detect_node(repo_path)
    if (repo_path / "pyproject.toml").exists() or (repo_path / "requirements.txt").exists():
        return _detect_python(repo_path)
    if (repo_path / "pom.xml").exists() or any(repo_path.glob("build.gradle*")):
        return DetectedRuntime("java", "21", _DEFAULT_PORT["java"], "Maven/Gradle project")
    if (repo_path / "go.mod").exists():
        return _detect_go(repo_path)
    if any(repo_path.glob("*.csproj")) or any(repo_path.glob("*.sln")):
        return DetectedRuntime("dotnet", "8.0", _DEFAULT_PORT["dotnet"], ".NET project")
    if (repo_path / "Gemfile").exists():
        return DetectedRuntime("ruby", "3.3", _DEFAULT_PORT["ruby"], "Ruby/Bundler project")
    if (repo_path / "composer.json").exists():
        return DetectedRuntime("php", "8.3", _DEFAULT_PORT["php"], "PHP/Composer project")
    return DetectedRuntime("generic", "latest", 8080, "Could not detect language from marker files")


def _detect_node(repo_path: Path) -> DetectedRuntime:
    version = "20"
    try:
        pkg = json.loads((repo_path / "package.json").read_text(encoding="utf-8"))
        engines_node = pkg.get("engines", {}).get("node", "")
        m = re.search(r"(\d+)", engines_node)
        if m:
            version = m.group(1)
    except Exception:
        pass
    return DetectedRuntime("node", version, _DEFAULT_PORT["node"], "Node.js project")


def _detect_python(repo_path: Path) -> DetectedRuntime:
    version = "3.12"
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'python\s*=\s*"[\^~]?(\d+\.\d+)', text)
        if m:
            version = m.group(1)
    return DetectedRuntime("python", version, _DEFAULT_PORT["python"], "Python project")


def _detect_go(repo_path: Path) -> DetectedRuntime:
    version = "1.22"
    text = (repo_path / "go.mod").read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^go (\d+\.\d+)", text, re.MULTILINE)
    if m:
        version = m.group(1)
    return DetectedRuntime("go", version, _DEFAULT_PORT["go"], "Go module project")
