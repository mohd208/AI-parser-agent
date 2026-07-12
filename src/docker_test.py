import subprocess
import threading
import time

from job_store import append_log

GRACE_SECONDS = 5  # how long to watch the container before deciding it's stable


def _pump(pipe, job_id, prefix, collected):
    for raw_line in iter(pipe.readline, ""):
        line = raw_line.rstrip("\n")
        if line:
            append_log(job_id, f"{prefix} {line}")
            collected.append(line)
    pipe.close()


def _run_streamed(args, cwd, job_id, prefix):
    append_log(job_id, f"$ {' '.join(args)}")
    proc = subprocess.Popen(
        args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    lines = []
    t = threading.Thread(target=_pump, args=(proc.stdout, job_id, prefix, lines))
    t.start()
    returncode = proc.wait()
    t.join()
    return returncode


def test_dockerfile(repo_dir, name, job_id):
    """Builds the Dockerfile Claude wrote and boots a container from it, to
    catch the class of bug a "looks correct" Dockerfile can still have — e.g.
    a CMD/ENTRYPOINT pointing at the wrong path, so the container builds fine
    but exits the instant it starts. Returns an outcome dict rather than
    raising: a failed smoke test is information about the Dockerfile, not a
    reason to discard it (Claude already wrote it, and the failure itself —
    plus the captured container logs — is exactly what's needed to fix it).
    """
    # Docker repository names must be lowercase; `name` comes straight from
    # the trigger payload (e.g. "AI-node-app") and would otherwise make
    # `docker build -t` reject the tag outright.
    slug = name.lower()
    image_tag = f"devops-ai-agent/{slug}:test"
    container_name = f"devops-ai-agent-{slug}-test"

    outcome = {"built": False, "started": False, "logs": None, "error": None, "imageTag": image_tag}

    try:
        # Clear out any leftover container from a previous run of this same
        # project, so a stale container can't be mistaken for this run's result.
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True)

        append_log(job_id, "Building Docker image to verify it works...")
        build_code = _run_streamed(
            ["docker", "build", "-t", image_tag, "."], cwd=repo_dir, job_id=job_id, prefix="[docker build]",
        )
        if build_code != 0:
            outcome["error"] = f"docker build failed (exit {build_code})"
            append_log(job_id, outcome["error"])
            return outcome
        outcome["built"] = True
        append_log(job_id, "Image built. Starting a container to confirm the app actually boots...")

        run_proc = subprocess.run(
            ["docker", "run", "-d", "--name", container_name, image_tag],
            cwd=repo_dir, capture_output=True, text=True,
        )
        if run_proc.returncode != 0:
            outcome["error"] = f"docker run failed to start: {run_proc.stderr.strip()}"
            append_log(job_id, outcome["error"])
            return outcome

        append_log(job_id, f"Container started, watching for {GRACE_SECONDS}s to confirm it doesn't crash on boot...")
        time.sleep(GRACE_SECONDS)

        status = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", container_name],
            capture_output=True, text=True,
        ).stdout.strip()

        logs_proc = subprocess.run(["docker", "logs", container_name], capture_output=True, text=True)
        outcome["logs"] = (logs_proc.stdout + logs_proc.stderr).strip()

        if status == "running":
            outcome["started"] = True
            append_log(job_id, "Container is running - Dockerfile smoke test passed")
        else:
            outcome["error"] = (
                f"Container exited early (status={status}); likely a bad CMD/ENTRYPOINT "
                f"path, missing runtime dependency, or a crash on startup"
            )
            append_log(job_id, outcome["error"])
            if outcome["logs"]:
                append_log(job_id, f"[container logs]\n{outcome['logs']}")

        return outcome
    except FileNotFoundError:
        outcome["error"] = "docker CLI not found on PATH - skipping Dockerfile smoke test"
        append_log(job_id, outcome["error"])
        return outcome
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True)
