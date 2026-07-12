import logging
import queue
import threading
import uuid
from datetime import datetime, timezone

log = logging.getLogger("devops-ai-agent.job_store")

_jobs = {}
_jobs_lock = threading.Lock()
_queue = queue.Queue()


def _now():
    return datetime.now(timezone.utc).isoformat()


def create_job(payload):
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "payload": payload,
        "status": "queued",
        "log": [],
        "result": None,
        "error": None,
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    with _jobs_lock:
        _jobs[job_id] = job
    _queue.put(job_id)
    return job


def get_job(job_id):
    with _jobs_lock:
        return _jobs.get(job_id)


def _update_job(job_id, **patch):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(patch)
        job["updatedAt"] = _now()


def append_log(job_id, line):
    """Records a log line on the job AND prints it live, so a single call
    site gives you both the `GET /jobs/:id` history and console/journald
    verbosity when this is running as a deployed service."""
    log.info("[%s] %s", job_id, line)
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["log"].append({"ts": _now(), "line": line})
        job["updatedAt"] = _now()


def start_worker(handler):
    """Runs jobs one at a time on a background thread, so repo clones and
    `claude` subprocesses never overlap."""

    def loop():
        while True:
            job_id = _queue.get()
            job = get_job(job_id)
            if job is None:
                continue
            log.info("[%s] Job started (payload=%s)", job_id, job["payload"])
            _update_job(job_id, status="running")
            try:
                result = handler(job)
                _update_job(job_id, status="done", result=result)
                log.info("[%s] Job finished: DONE", job_id)
            except Exception as exc:
                _update_job(job_id, status="failed", error=str(exc))
                append_log(job_id, f"ERROR: {exc}")
                log.info("[%s] Job finished: FAILED", job_id)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
