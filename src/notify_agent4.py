import json
import os
import urllib.error
import urllib.request

from job_store import append_log

# Agent 4 (GitHub Actions workflow generation) runs as its own service — see
# ../../github-workflow-agent — on a different port than this one.
AGENT4_URL = os.environ.get("AGENT4_URL", "http://localhost:4003/trigger")


def notify_agent4(payload, job_id):
    """POSTs the handoff to agent 4, in parallel with agents 2 and 3 (see
    fan_out.py). Agent 4 doesn't need anything agent 3 produces — the
    manifest directory path and K8s namespace are both derived from a fixed
    convention, not from agent 3's actual output — so it doesn't need to
    wait for it either."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        AGENT4_URL, data=data, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            append_log(job_id, f"Notified agent 4 at {AGENT4_URL} (status {response.status})")
    except urllib.error.URLError as exc:
        append_log(job_id, f"Could not notify agent 4 at {AGENT4_URL}: {exc}")
