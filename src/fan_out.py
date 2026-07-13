import threading

from job_store import append_log
from notify_agent2 import notify_agent2
from notify_agent3 import notify_agent3
from notify_agent4 import notify_agent4


def fan_out_to_downstream_agents(payload, job_id):
    """Dispatches the same handoff payload to agents 2 (image push), 3 (K8s
    manifests) and 4 (GitHub workflow) at the same time, instead of chaining
    them one after another — none of the three actually needs another one's
    output: agent 3 predicts the image tag agent 2 will push (both derive it
    from the same imageTagSuffix), and agent 4 derives the manifest path/
    namespace from a fixed convention rather than agent 3's actual result.

    Note: this trades sequential safety for speed. If agent 2's push fails,
    agent 3's manifest will still reference the tag as if it succeeded —
    there's no rollback between these three. Check each agent's own job log
    to confirm its part actually worked.
    """
    targets = [
        ("agent 2 (image push)", notify_agent2),
        ("agent 3 (K8s manifests)", notify_agent3),
        ("agent 4 (GitHub workflow)", notify_agent4),
    ]

    append_log(job_id, "Fanning out to agents 2, 3 and 4 in parallel...")
    threads = [threading.Thread(target=notify_fn, args=(payload, job_id)) for _, notify_fn in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
