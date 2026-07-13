import json
import os
import urllib.error
import urllib.request

from job_store import append_log

# Agent 3 (K8s manifest generation) runs as its own service — see
# ../../k8s-manifest-agent — on a different port than this one.
AGENT3_URL = os.environ.get("AGENT3_URL", "http://localhost:4002/trigger")


def notify_agent3(payload, job_id):
    """POSTs the handoff to agent 3, in parallel with agents 2 and 4 (see
    fan_out.py) rather than waiting for agent 2's image push to finish —
    agent 3 predicts the same image tag agent 2 will push to, using the
    shared deterministic imageTagSuffix, so it doesn't need to wait."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        AGENT3_URL, data=data, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            append_log(job_id, f"Notified agent 3 at {AGENT3_URL} (status {response.status})")
    except urllib.error.URLError as exc:
        append_log(job_id, f"Could not notify agent 3 at {AGENT3_URL}: {exc}")
