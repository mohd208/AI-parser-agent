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
        "  If you do, double-check every COPY --from=<stage> source actually gets created in that stage — e.g. a Node",
        "  package with zero dependencies won't produce a node_modules directory at all, which breaks a later COPY of it.",
        "  When there's nothing to gain from staging (no real deps to cache separately), prefer a single-stage build instead.",
        "- Run the final process as a non-root user.",
        "- Only copy in what's needed for the build/runtime (leverage layer caching for dependency installs).",
        "- Expose the port the app actually listens on, if you can determine it.",
        "- Add a .dockerignore file if one doesn't already exist.",
        "",
        "Do not modify any files other than creating/updating the Dockerfile and .dockerignore.",
        "When finished, reply with ONLY a compact JSON object (no markdown fences) with this shape:",
        '{"language": string, "framework": string|null, "baseImage": string, "port": number|null, '
        '"filesWritten": string[], "notes": string}',
        '("port" is the container port EXPOSEd in the Dockerfile, or null if the app doesn\'t listen on one.)',
    ])


def _strip_code_fence(text):
    """Claude is told to reply with raw JSON, no markdown fences, but doesn't
    always comply — strip a leading/trailing ``` (optionally ```json) before
    parsing so a fenced reply doesn't get treated as unparseable."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.strip()
        if text.endswith("```"):
            text = text[: -len("```")]
    return text.strip()


def _describe_event(event):
    """Turns one stream-json event into short human-readable line(s) instead
    of the raw event JSON. Returns None for bookkeeping event types that
    aren't worth showing (tool results being fed back, etc.)."""
    etype = event.get("type")

    if etype == "system" and event.get("subtype") == "init":
        return [f"Claude session started (model={event.get('model')})"]

    if etype == "assistant":
        lines = []
        for block in (event.get("message") or {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                lines.append(f"Claude: {block['text'].strip()}")
            elif block.get("type") == "tool_use":
                tool_input = block.get("input", {})
                detail = tool_input.get("file_path") or tool_input.get("command") or tool_input.get("pattern") or ""
                lines.append(f"Claude is using {block.get('name')}: {detail}".strip())
        return lines or None

    return None


def _pump_events(pipe, job_id, events):
    """Reads newline-delimited stream-json events as they're emitted and logs
    a concise description of each one live, instead of waiting for the whole
    run to finish and dumping one giant blob."""
    for raw_line in iter(pipe.readline, ""):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        for line in _describe_event(event) or []:
            append_log(job_id, line)
    pipe.close()


def _pump_stderr(pipe, job_id):
    for raw_line in iter(pipe.readline, ""):
        line = raw_line.rstrip("\n")
        if line:
            append_log(job_id, f"[claude:stderr] {line}")
    pipe.close()


def generate_dockerfile(repo_dir, environment, name, job_id):
    """Runs Claude Code headless (`claude -p`) inside `repo_dir`, authenticated
    via the Pro/Max subscription session (not an API key), to analyze the repo
    and write a Dockerfile. `acceptEdits` auto-approves file writes; Bash
    beyond the read-only allowlist below would still prompt, which would hang
    an unattended run, so we deliberately don't grant more than that.

    `--output-format stream-json` emits one JSON event per line as things
    happen (session init, each tool call, the final result), which is what
    actually streams live — plain `json` output only gets flushed as a single
    blob once the whole run is over, since the CLI fully buffers stdout when
    it isn't attached to a TTY.
    """
    prompt = _build_prompt(environment, name)

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)  # force use of the subscription login, not API billing

    args = [
        "claude",
        # NOT --bare: it isolates the run into a config/session context that
        # doesn't see the `/login`-persisted subscription auth, which is why
        # headless runs failed "Not logged in" even with a working login.
        "-p", prompt,
        "--add-dir", ".",
        "--permission-mode", "acceptEdits",
        "--allowedTools", ALLOWED_TOOLS,
        "--output-format", "stream-json",
        "--verbose",  # required by the CLI whenever --print is combined with stream-json
    ]

    append_log(job_id, "Starting Claude Code analysis...")

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

    events = []
    t_out = threading.Thread(target=_pump_events, args=(proc.stdout, job_id, events))
    t_err = threading.Thread(target=_pump_stderr, args=(proc.stderr, job_id))
    t_out.start()
    t_err.start()

    returncode = proc.wait()
    t_out.join()
    t_err.join()

    result_event = next((e for e in reversed(events) if e.get("type") == "result"), None)

    if returncode != 0 or (result_event and result_event.get("is_error")):
        message = result_event.get("result") if result_event else f"claude exited with code {returncode}"
        raise RuntimeError(f"Claude run failed: {message}")

    if result_event is None:
        raise RuntimeError("claude finished but produced no result event")

    try:
        summary = json.loads(_strip_code_fence(result_event["result"]))
    except (json.JSONDecodeError, KeyError, TypeError):
        summary = {"raw": result_event.get("result")}

    return {
        "summary": summary,
        "costUsd": result_event.get("total_cost_usd"),
        "sessionId": result_event.get("session_id"),
    }
