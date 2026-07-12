import logging
import os

from flask import Flask, jsonify, request

from claude_runner import generate_dockerfile
from docker_test import test_dockerfile
from git_sync import sync_repo
from job_store import append_log, create_job, get_job, start_worker
from lang_detect import quick_scan
from notify_agent2 import notify_agent2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("devops-ai-agent")

app = Flask(__name__)


@app.post("/trigger")
def trigger():
    body = request.get_json(silent=True) or {}
    log.info("Received /trigger request: %s", body)

    repo_url = body.get("repoUrl")
    name = body.get("name")
    branch = body.get("branch")
    environment = body.get("environment")

    if not all([repo_url, name, branch, environment]):
        log.warning("Rejected /trigger request, missing field(s): %s", body)
        return jsonify(error="repoUrl, name, branch and environment are all required"), 400

    job = create_job({"repoUrl": repo_url, "name": name, "branch": branch, "environment": environment})
    log.info("Queued job %s for %s (branch=%s, env=%s)", job["id"], name, branch, environment)
    return jsonify(jobId=job["id"], status=job["status"]), 202


@app.get("/jobs/<job_id>")
def job_status(job_id):
    job = get_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404
    return jsonify(job)


def handle_job(job):
    job_id = job["id"]
    payload = job["payload"]
    repo_url, name, branch, environment = (
        payload["repoUrl"], payload["name"], payload["branch"], payload["environment"],
    )

    # Phase 1: fetch the code.
    append_log(job_id, f"Syncing {repo_url} ({branch})")
    repo_dir = sync_repo(repo_url, name, branch, job_id=job_id)

    # Phase 2: analyze — a fast deterministic manifest scan first (instant
    # signal), then Claude's own (authoritative) analysis as part of the call
    # below that also writes the Dockerfile.
    append_log(job_id, "Analyzing repository to detect the programming language...")
    hints = quick_scan(repo_dir)
    if hints:
        append_log(job_id, f"Quick scan found: {', '.join(hints)}")
    else:
        append_log(job_id, "Quick scan found no recognizable manifest files; deferring to Claude's analysis")

    # Phase 3: decide + create the Dockerfile.
    append_log(job_id, "Asking Claude to confirm the language/framework and write the Dockerfile...")
    result = generate_dockerfile(repo_dir, environment, name, job_id=job_id)
    summary = result.get("summary", {})
    append_log(
        job_id,
        f"Decision -> language={summary.get('language')} "
        f"framework={summary.get('framework')} baseImage={summary.get('baseImage')}",
    )

    # Phase 4: prove the Dockerfile actually works, don't just trust it.
    append_log(job_id, "Testing the generated Dockerfile (docker build + run)...")
    result["dockerTest"] = test_dockerfile(repo_dir, name, job_id=job_id)

    # Phase 5: hand off to agent 2 (build/publish) — only if we actually have
    # a built image; a smoke-test crash (e.g. the container not staying up)
    # doesn't block this, only a failed `docker build` does.
    if result["dockerTest"].get("built"):
        append_log(job_id, "Handing off to agent 2 for image publish...")
        notify_agent2(
            {
                "appName": name,
                "environment": environment,
                "imageTag": result["dockerTest"]["imageTag"],
                "repoDir": str(repo_dir),
                "port": summary.get("port"),
                "language": summary.get("language"),
                "framework": summary.get("framework"),
                "sourceJobId": job_id,
            },
            job_id=job_id,
        )
    else:
        append_log(job_id, "Skipping handoff to agent 2: Docker image was not successfully built")

    append_log(job_id, "Job complete")
    return result


start_worker(handle_job)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 4000))
    log.info("devops-ai-agent listening on :%s", port)
    app.run(host="0.0.0.0", port=port)
