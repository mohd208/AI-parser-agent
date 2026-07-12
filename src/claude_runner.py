import json
import os
import platform
import subprocess

READ_ONLY_BASH = ["Bash(ls *)", "Bash(cat *)", "Bash(pwd)", "Bash(find *)", "Bash(grep *)"]
ALLOWED_TOOLS = ",".join(["Read", "Write", *READ_ONLY_BASH])

# On Windows, global npm installs (like the claude CLI) are .cmd shims that
# Windows can't exec directly via CreateProcess — they need a shell to run.
# On Linux/macOS the real binary is on PATH, so no shell is needed.
_USE_SHELL = platform.system() == "Windows"


def _build_prompt(environment, name):
    return "\n".join([
        f'You are working inside a freshly cloned copy of the "{name}" repository, checked out at the repo root.',
        "Analyze the codebase to determine its primary programming language, framework, and runtime version",
        "(check manifest files such as package.json, requirements.txt, go.mod, pom.xml, Gemfile, etc., and lockfiles for exact versions).",
        "",
        f'Then create a production-ready Dockerfile in the repo root suited for the "{environment}" environment. Follow best practices:',
        '- Pin a specific base image tag (no ":latest").',
        "- Use a multi-stage build if the language/framework benefits from it (e.g. compiled languages, or separating build deps from runtime deps).",
        "- Run the final process as a non-root user.",
        "- Only copy in what's needed for the build/runtime (leverage layer caching for dependency installs).",
        "- Expose the port the app actually listens on, if you can determine it.",
        "- Add a .dockerignore file if one doesn't already exist.",
        "",
        "Do not modify any files other than creating/updating the Dockerfile and .dockerignore.",
        "When finished, reply with ONLY a compact JSON object (no markdown fences) with this shape:",
        '{"language": string, "framework": string|null, "baseImage": string, "filesWritten": string[], "notes": string}',
    ])


def generate_dockerfile(repo_dir, environment, name):
    """Runs Claude Code headless (`claude -p`) inside `repo_dir`, authenticated
    via the Pro/Max subscription session (not an API key), to analyze the repo
    and write a Dockerfile. `acceptEdits` auto-approves file writes; Bash
    beyond the read-only allowlist below would still prompt, which would hang
    an unattended run, so we deliberately don't grant more than that.
    """
    prompt = _build_prompt(environment, name)

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)  # force use of the subscription login, not API billing

    args = [
        "claude",
        "--bare",
        "-p", prompt,
        "--add-dir", ".",
        "--permission-mode", "acceptEdits",
        "--allowedTools", ALLOWED_TOOLS,
        "--output-format", "json",
    ]

    proc = subprocess.run(
        args,
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
        shell=_USE_SHELL,
    )

    if proc.returncode != 0:
        raise RuntimeError(f"claude exited with code {proc.returncode}: {proc.stderr or proc.stdout}")

    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Could not parse claude output as JSON: {proc.stdout}")

    try:
        summary = json.loads(parsed["result"])
    except (json.JSONDecodeError, KeyError, TypeError):
        summary = {"raw": parsed.get("result")}

    return {
        "summary": summary,
        "costUsd": parsed.get("total_cost_usd"),
        "sessionId": parsed.get("session_id"),
    }
