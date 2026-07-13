# Setup checklist

Everything below is something *you* need to create or configure. Nothing in
this repo will work end-to-end until these exist.

## 1. AWS Secrets Manager — 3 secrets

Create these three secrets (names are configurable via `SECRET_NAME_TEMPLATE`
in `.env`, default `devops-agent/{environment}`):

- `devops-agent/dev`
- `devops-agent/staging`
- `devops-agent/prod`

Each is a JSON blob with the same keys:

```json
{
  "GITHUB_TOKEN": "ghp_... or GitHub App installation token",
  "DATADOG_API_KEY": "...",
  "DATADOG_APP_KEY": "...",
  "AWS_REGION": "us-east-1",
  "EKS_CLUSTER_NAME": "eks-dev",
  "EKS_OIDC_PROVIDER_ARN": "arn:aws:iam::123456789012:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/XXXXX",
  "GITHUB_OIDC_ROLE_ARN": "arn:aws:iam::123456789012:role/github-actions-devops-agent",
  "TF_STATE_BUCKET": "yourco-tfstate-devops-agent",
  "TF_LOCK_TABLE": "yourco-tfstate-lock"
}
```

The `EKS_OIDC_PROVIDER_ARN`, `TF_STATE_BUCKET`, `TF_LOCK_TABLE`, and
`GITHUB_OIDC_ROLE_ARN` values come out of `bootstrap-infra` (step 3) — apply
that first, then copy its outputs into these secrets.

**These six values (everything except `GITHUB_TOKEN`/`DATADOG_*`) get copied
automatically** into a GitHub Environment (named `dev`/`staging`/`prod`) on
every app repo the agent touches, as plain Actions Variables — that's what
the generated Terraform/workflows actually read at run time (see
[ARCHITECTURE.md](ARCHITECTURE.md#config-lives-in-github-not-in-committed-files)).
Secrets Manager is just where the orchestrator gets the *initial* values from;
once seeded, you can edit them directly on the app repo under **Settings →
Environments → \<env\> → Variables** without touching Secrets Manager or
re-running the ticket.

**IAM permission needed by the orchestrator server itself:**

```json
{
  "Effect": "Allow",
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "arn:aws:secretsmanager:*:*:secret:devops-agent/*"
}
```
Attach to whatever role/user the server uses (instance profile if it's EC2,
or an access key in its own environment — do **not** put AWS keys in this
repo's `.env`; use an instance role if at all possible).

## 2. GitHub — token/app + OIDC

- **Token**: a fine-grained PAT (or better, a GitHub App installation token)
  with `Contents: read/write`, `Pull requests: read/write`, `Workflows:
  read/write` (required because the agent commits into
  `.github/workflows/**`), and `Environments: read/write` (required to create
  the dev/staging/prod GitHub Environment and its Variables — see above).
  Store it as `GITHUB_TOKEN` inside each of the 3 secrets above (can be the
  same token for all three, or per-env if you use separate GitHub orgs/apps).
- **OIDC**: `bootstrap-infra` creates the `token.actions.githubusercontent.com`
  identity provider and an IAM role trusted for your org's repos. You only
  need to tell it your GitHub org name via `github_org` variable.
- Optional: a reviewer team/usernames if you want a human auto-requested on
  every PR alongside the Claude review (`PR_REVIEWERS` in `.env`).

## 3. `bootstrap-infra/` — run once per AWS account

```powershell
cd bootstrap-infra
terraform init
terraform apply -var="github_org=your-org" -var="aws_region=us-east-1" -var="datadog_api_key=..."
```

Creates: S3 state bucket + DynamoDB lock table, GitHub OIDC provider + IAM
role, three EKS clusters (`eks-dev`/`eks-staging`/`eks-prod`) — **skip cluster
creation and instead import existing cluster names/ARNs if you already have
them** (see comments in `bootstrap-infra/main.tf`) — and the Datadog cluster
agent (Helm release) on each cluster using `datadog_api_key`.

Copy the `terraform output` values into the three Secrets Manager secrets from
step 1.

## 4. Datadog

- Org Settings → API Keys → create one, and an Application Key. Both go into
  every environment secret (`DATADOG_API_KEY`, `DATADOG_APP_KEY`) and into
  `bootstrap-infra`'s `datadog_api_key` variable.

## 5. Jira Automation rule

See [../jira/automation-rule.md](../jira/automation-rule.md) for the exact
rule config (trigger, JSON body, smart values). You'll need:

- An issue type or label to filter on (e.g. `DevOps Provision`).
- Four fields on that issue type: Application Name, GitHub URL, Environment
  (single-select: dev/staging/prod), Branch Name — note their custom field
  IDs (**Issue → ... → Export → find field ID**, or just use the field *names*
  in the automation rule's smart values, which is simpler and what the sample
  rule uses).
- A shared secret string — set it as `WEBHOOK_SECRET` in the orchestrator's
  `.env` and as a header (`X-Webhook-Secret`) in the Jira automation's "Send
  web request" action.

## 6. The server running the orchestrator

- Claude CLI already installed & logged in (confirmed — your Pro subscription
  session). Sanity check: `claude -p "say ok" --output-format json` should
  return JSON, not an auth prompt.
- Python 3.11+, `git`.
- Inbound HTTPS reachable from Jira Cloud on whatever port/path you expose
  `/webhook/jira` at (a reverse proxy + real TLS cert, or a Cloudflare
  Tunnel/ngrok if this is still in testing).
- Outbound access to: GitHub (HTTPS), AWS APIs, and wherever `claude` CLI
  needs to reach for its own API calls.

## 7. `.env` for the orchestrator

Copy `orchestrator/.env.example` to `orchestrator/.env` and fill in:
`WEBHOOK_SECRET`, `AWS_REGION`, `SECRET_NAME_TEMPLATE`, `GITHUB_BASE_BRANCH`
(default branch PRs target, usually `main`), `CLAUDE_CLI_PATH` (usually just
`claude`), `WORKDIR` (scratch dir for clones).

---

Once all of the above exists, start the orchestrator (see README) and create a
test Jira ticket to run the flow end to end against a throwaway repo before
pointing it at anything real.
