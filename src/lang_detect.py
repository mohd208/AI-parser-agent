from pathlib import Path

# manifest filename -> language label. This is a fast, deterministic sniff —
# no AI involved — so it can report something the instant the repo is synced,
# before Claude's slower (but authoritative) analysis finishes.
_MANIFESTS = [
    ("package.json", "Node.js"),
    ("requirements.txt", "Python"),
    ("pyproject.toml", "Python"),
    ("Pipfile", "Python"),
    ("go.mod", "Go"),
    ("pom.xml", "Java (Maven)"),
    ("build.gradle", "Java/Kotlin (Gradle)"),
    ("build.gradle.kts", "Java/Kotlin (Gradle)"),
    ("Gemfile", "Ruby"),
    ("composer.json", "PHP"),
    ("Cargo.toml", "Rust"),
]

_DOTNET_GLOBS = ("*.csproj", "*.sln", "*.fsproj")


def quick_scan(repo_dir):
    repo_dir = Path(repo_dir)
    hits = []

    for filename, language in _MANIFESTS:
        if (repo_dir / filename).exists():
            hits.append(f"{language} ({filename})")

    for pattern in _DOTNET_GLOBS:
        if next(repo_dir.glob(pattern), None) is not None:
            hits.append(f".NET ({pattern})")
            break

    return hits
