import json
import os
import platform
import subprocess
import threading

from job_store import append_log

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


def _pump(pipe, job_id, prefix, collected):
    """Reads a subprocess pipe line-by-line as output arrives and forwards
    each line through append_log (console + job history) in real time,
    instead of waiting for the process to exit."""
    for raw_line in iter(pipe.readline, ""):
        line = raw_line.rstrip("\n")
        if line:
            append_log(job_id, f"{prefix} {line}")
            collected.append(line)
    pipe.close()


def generate_dockerfile(repo_dir, environment, name, job_id):
    """Runs Claude Code headless (`claude -p`) inside `repo_dir`, authenticated
    via the Pro/Max subscription session (not an API key), to analyze the repo
    and write a Dockerfile. `acceptEdits` auto-approves file writes; Bash
    beyond the read-only allowlist below would still prompt, which would hang
    an unattended run, so we deliberately don't grant more than that.

    `--verbose` makes Claude Code narrate each tool call (reads, writes) on
    stderr as it happens; we stream that live via append_log instead of only
    surfacing the final result once the whole run is done.
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
        "--verbose",
    ]

    append_log(job_id, f"$ claude --bare -p <prompt> --add-dir . --permission-mode acceptEdits "
                        f"--allowedTools {ALLOWED_TOOLS} --output-format json --verbose")

    proc = subprocess.Popen(
        args,
        cwd=repo_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        shell=_USE_SHELL,
    )

    stdout_lines, stderr_lines = [], []
    t_out = threading.Thread(target=_pump, args=(proc.stdout, job_id, "[claude]", stdout_lines))
    t_err = threading.Thread(target=_pump, args=(proc.stderr, job_id, "[claude:verbose]", stderr_lines))
    t_out.start()
    t_err.start()

    returncode = proc.wait()
    t_out.join()
    t_err.join()

    stdout = "\n".join(stdout_lines)
    stderr = "\n".join(stderr_lines)

    if returncode != 0:
        raise RuntimeError(f"claude exited with code {returncode}: {stderr or stdout}")

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Could not parse claude output as JSON: {stdout}")

    try:
        summary = json.loads(parsed["result"])
    except (json.JSONDecodeError, KeyError, TypeError):
        summary = {"raw": parsed.get("result")}

    append_log(job_id, f"Claude summary: {summary}")

    return {
        "summary": summary,
        "costUsd": parsed.get("total_cost_usd"),
        "sessionId": parsed.get("session_id"),
    }
