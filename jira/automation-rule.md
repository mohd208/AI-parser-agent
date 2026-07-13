# Jira Automation rule

Project settings → Automation → Create rule.

## Trigger
**Issue created**
JQL filter (adjust to your project/issue type):
```
project = "YOUR_PROJECT" AND issuetype = "DevOps Provision"
```

## Condition (optional but recommended)
**Field value changed / Issue fields condition** — require the four fields to
be non-empty so malformed tickets don't reach the webhook:
- Application Name is not empty
- GitHub URL is not empty
- Environment is not empty
- Branch Name is not empty

## Action: Send web request
- **URL**: `https://<your-server-domain>/webhook/jira`
- **Method**: POST
- **Headers**:
  - `Content-Type: application/json`
  - `X-Webhook-Secret: <same value as WEBHOOK_SECRET in orchestrator/.env>`
- **Custom data (JSON body)** — use smart values referencing your fields *by
  name* (safer than customfield IDs, which change between Jira instances):

```json
{
  "issue_key": "{{issue.key}}",
  "application_name": "{{issue.Application Name}}",
  "github_url": "{{issue.GitHub URL}}",
  "environment": "{{issue.Environment}}",
  "branch_name": "{{issue.Branch Name}}",
  "reporter_email": "{{issue.reporter.emailAddress}}"
}
```

If smart-value-by-name doesn't resolve for a custom field in your instance,
fall back to the customfield ID form: `{{issue.customfield_10050}}` (find the
ID via issue → **... (more)** → **Export** in older Jira, or the field's URL
in field configuration).

- **Response type**: JSON, and it's worth adding a "Then" branch that comments
  back on the issue with the response body (the orchestrator returns
  `{"status":"accepted","tracking_id":"..."}` immediately, `202`) so the
  reporter sees confirmation the ticket was picked up.

## Notes
- The orchestrator validates the four required fields itself and returns
  `400` with a clear message if any are missing — the Jira-side condition
  above is a nice-to-have, not a hard requirement.
- `environment` must be exactly one of `dev`, `staging`, `prod` (case
  sensitive) — that's what selects which of the three Secrets Manager secrets
  gets pulled. Make the Jira field a single-select with exactly those three
  options to avoid typos.
