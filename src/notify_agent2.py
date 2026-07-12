import json
import os
import urllib.error
import urllib.request

from job_store import append_log

# Agent 2 (image build/publish) runs as its own service — see
# ../../image-publish-agent — on a different port than this one.
AGENT2_URL = os.environ.get("AGENT2_URL", "http://localhost:4001/trigger")


def notify_agent2(payload, job_id):
    """POSTs the handoff to agent 2 once agent 1's Dockerfile has been
    generated and successfully built. This is a plain HTTP call to a
    separate service, so a failure here doesn't undo agent 1's own result —
    the Dockerfile was still written either way."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        AGENT2_URL, data=data, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            append_log(job_id, f"Notified agent 2 at {AGENT2_URL} (status {response.status})")
    except urllib.error.URLError as exc:
        append_log(job_id, f"Could not notify agent 2 at {AGENT2_URL}: {exc}")
