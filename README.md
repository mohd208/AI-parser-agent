# DevOps AI Agent

Jira-triggered, Claude-powered provisioning agent. A Jira ticket (issue type
`DevOps Provision`) with four fields — **Application Name**, **GitHub URL**,
**Environment**, **Branch Name** — kicks off an end-to-end flow that:

1. Clones the target repo at the given branch.
2. Detects the language/runtime and generates a Dockerfile.
3. Generates Kubernetes manifests (namespace, deployment, service, ingress, HPA,
   IRSA service account) tagged for Datadog.
4. Generates Terraform for that app (ECR repo, IRSA IAM role) that plugs into
   a **shared, already-provisioned** EKS cluster per environment (dev/staging/
   prod) — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for why we don't
   spin up a cluster per app. Every resource is named
   `<application-name>-<environment>` (ECR repo, IAM role, K8s namespace and
   objects), and the infra pipeline checks AWS first and **imports** the ECR
   repo/IAM role instead of failing if they already exist.
5. Generates two GitHub Actions workflows in the app repo: `infra-terraform.yml`
   and `deploy.yml`, wired for AWS OIDC (no static AWS keys in GitHub). Neither
   file hardcodes an AWS account/region/cluster — they read `vars.AWS_REGION`,
   `vars.EKS_CLUSTER_NAME`, etc. from a GitHub Environment variable set.
6. Pulls environment-specific config (GitHub token, Datadog keys, AWS/EKS
   identifiers) from AWS Secrets Manager based on the `environment` field, and
   seeds it into that GitHub Environment as plain Variables you can edit by
   hand afterward (Settings → Environments → dev/staging/prod → Variables).
7. Runs a Claude Code (`claude -p`) pass to review/clean up everything it just
   generated, commits, pushes, and opens a PR against the ticket's branch.
8. Runs a second Claude-driven PR review pass; if it finds issues it fixes them
   and pushes another commit to the same PR.
9. On merge: `infra-terraform.yml` runs first (creates/updates the ECR repo +
   IAM role), then `deploy.yml` runs (build image → push to ECR → deploy to the
   shared EKS cluster), triggered via `workflow_run` so ordering is guaranteed.

## Layout

```
devops-ai-agent/
  orchestrator/          # the service that runs on your server
    app/                 # webhook listener + pipeline code
    templates/            # Dockerfile / k8s / terraform / workflow templates
  bootstrap-infra/        # ONE-TIME terraform: OIDC provider, EKS clusters,
                           # S3 state bucket + lock table, Datadog cluster agent
  jira/                   # Jira Automation rule setup instructions
  docs/
    ARCHITECTURE.md       # full design + data flow
    SETUP.md              # everything YOU need to create/configure
  scripts/                # run helpers
```

## Quick start

See [docs/SETUP.md](docs/SETUP.md) — it lists every secret, IAM permission, and
GitHub/Jira configuration step required before this will run end to end.

```powershell
cd orchestrator
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # fill in values, see docs/SETUP.md
uvicorn app.main:app --host 0.0.0.0 --port 8080
```
