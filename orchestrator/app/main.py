import logging
import uuid

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import ValidationError

from .config import settings
from .models import JiraTicket
from .pipeline import run as run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

app = FastAPI(title="devops-ai-agent")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook/jira", status_code=202)
def jira_webhook(
    payload: dict,
    background_tasks: BackgroundTasks,
    x_webhook_secret: str | None = Header(default=None),
):
    if x_webhook_secret != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="invalid webhook secret")

    try:
        ticket = JiraTicket(**payload)
    except ValidationError as e:
        # include_context=False: pydantic v2 embeds the raw exception object
        # (e.g. the ValueError a field_validator raised) in each error's
        # "ctx" key, which isn't JSON-serializable and would 500 here instead
        # of returning the intended 400.
        raise HTTPException(status_code=400, detail=e.errors(include_context=False, include_url=False))

    request_id = str(uuid.uuid4())[:8]
    log.info("[%s] accepted ticket %s for %s", request_id, ticket.issue_key, ticket.application_name)

    background_tasks.add_task(_run_safely, request_id, ticket)
    return {"status": "accepted", "tracking_id": request_id, "issue_key": ticket.issue_key}


def _run_safely(request_id: str, ticket: JiraTicket) -> None:
    try:
        run_pipeline(ticket)
    except Exception:
        log.exception("[%s] pipeline failed for %s", request_id, ticket.issue_key)
