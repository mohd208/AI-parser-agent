from pathlib import Path

from .claude_engine import run_claude
from .config import settings
from .git_ops import commit_all, push

_REVIEW_PROMPT = """You are a senior DevOps engineer reviewing infrastructure code before it
ships. Run `git diff {base_branch}...HEAD` to see everything that changed on this branch.

Review the Dockerfile, everything under k8s/, everything under terraform/, and
the .github/workflows/*.yml files that were just added for:
- correctness (Dockerfile actually builds and runs the detected app; k8s
  manifests reference the right ports/images; terraform resources are
  internally consistent; workflow YAML is valid and the AWS OIDC role/ECR/EKS
  names line up across files)
- obvious security issues (containers running as root without reason,
  overly-broad IAM policies, secrets hardcoded instead of referenced)
- consistency (app name/namespace/environment spelled the same way everywhere)

If everything looks correct, respond with exactly: NO_ISSUES
Otherwise, directly fix every issue you find by editing the files in this
repo, then respond with a short bullet list summarizing what you changed and
why. Do not ask questions — make the calls a senior engineer would make.
"""


def run(repo_path: Path, base_branch: str, branch_name: str) -> str:
    """Runs up to `claude_review_max_iterations` review passes. Each pass may
    edit files directly; if it does, we commit + push so the same PR is
    updated. Returns a human-readable summary for the PR comment.
    """
    summary_parts = []
    for i in range(settings.claude_review_max_iterations):
        result = run_claude(
            _REVIEW_PROMPT.format(base_branch=base_branch),
            cwd=repo_path,
            allowed_tools="Read,Write,Edit,Glob,Grep,Bash(git diff:*)",
        )
        if not result.ok:
            summary_parts.append(f"Review pass {i + 1} failed to run: {result.text}")
            break

        text = result.text.strip()
        if text.startswith("NO_ISSUES"):
            summary_parts.append(f"Review pass {i + 1}: no issues found.")
            break

        summary_parts.append(f"Review pass {i + 1} made changes:\n{text}")
        if commit_all(repo_path, f"AI review fix pass {i + 1}"):
            push(repo_path, branch_name)
        else:
            # Claude reported changes but nothing was actually staged - stop.
            break

    return "\n\n".join(summary_parts)
