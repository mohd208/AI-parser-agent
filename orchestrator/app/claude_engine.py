import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import settings


@dataclass
class ClaudeResult:
    ok: bool
    text: str
    raw: dict | None = None


def run_claude(
    prompt: str,
    cwd: Path,
    allowed_tools: str = "Read,Write,Edit,Glob,Grep,Bash(git diff:*)",
    timeout_seconds: int = 600,
) -> ClaudeResult:
    """Invoke the local Claude Code CLI headlessly (non-interactive `-p` /
    print mode) with cwd set to the cloned repo, so Claude can read the repo
    and directly write/edit files with its own tools.

    Runs unattended (no human to approve edits), so we scope --allowedTools
    tightly per call instead of using --dangerously-skip-permissions.
    """
    args = [
        settings.claude_cli_path,
        "-p", prompt,
        "--output-format", "json",
        "--permission-mode", settings.claude_permission_mode,
        "--allowedTools", allowed_tools,
    ]
    try:
        result = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True,
            timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired:
        return ClaudeResult(ok=False, text=f"claude CLI timed out after {timeout_seconds}s")

    if result.returncode != 0:
        return ClaudeResult(ok=False, text=result.stderr or result.stdout)

    try:
        payload = json.loads(result.stdout)
        text = payload.get("result", result.stdout)
        return ClaudeResult(ok=True, text=text, raw=payload)
    except json.JSONDecodeError:
        return ClaudeResult(ok=True, text=result.stdout, raw=None)
