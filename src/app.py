import os

from flask import Flask, jsonify, request

from claude_runner import generate_dockerfile
from git_sync import sync_repo
from job_store import append_log, create_job, get_job, start_worker

app = Flask(__name__)


@app.post("/trigger")
def trigger():
    body = request.get_json(silent=True) or {}
    repo_url = body.get("repoUrl")
    name = body.get("name")
    branch = body.get("branch")
    environment = body.get("environment")

    if not all([repo_url, name, branch, environment]):
        return jsonify(error="repoUrl, name, branch and environment are all required"), 400

    job = create_job({"repoUrl": repo_url, "name": name, "branch": branch, "environment": environment})
    return jsonify(jobId=job["id"], status=job["status"]), 202


@app.get("/jobs/<job_id>")
def job_status(job_id):
    job = get_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404
    return jsonify(job)


def handle_job(job):
    payload = job["payload"]
    repo_url, name, branch, environment = (
        payload["repoUrl"], payload["name"], payload["branch"], payload["environment"],
    )

    append_log(job["id"], f"Syncing {repo_url} ({branch})")
    repo_dir = sync_repo(repo_url, name, branch)

    append_log(job["id"], f"Running Claude Code against {repo_dir}")
    result = generate_dockerfile(repo_dir, environment, name)
    append_log(job["id"], "Claude Code run complete")

    return result


start_worker(handle_job)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 4000))
    app.run(host="0.0.0.0", port=port)
