# Architecture

## Flow

```
Jira "DevOps Provision" ticket created
        |  (Jira Automation: "Send web request")
        v
POST /webhook/jira  (FastAPI, orchestrator/app/main.py)
        |  validates required fields + shared-secret header
        v
pipeline.run(ticket)                       [orchestrator/app/pipeline.py]
        |
        |-- 1. secrets_manager.get_secret(environment)   AWS Secrets Manager
        |       -> devops-agent/dev | devops-agent/staging | devops-agent/prod
        |
        |-- 2. git_ops.clone + checkout/create branch (ticket.branch_name)
        |
        |-- 3. language_detect.detect(repo)              heuristic (package.json, requirements.txt, pom.xml, go.mod, *.csproj ...)
        |
        |-- 4. github_api.ensure_environment() + upsert_environment_variable()  x7
        |       creates the GitHub Environment named "{environment}" on the app
        |       repo and seeds it with AWS_REGION/EKS_CLUSTER_NAME/etc. as plain
        |       (editable) Actions Variables — see "Config lives in GitHub" below
        |
        |-- 5. dockerfile_gen.generate()                 Jinja2 template per language (skipped if Dockerfile already exists)
        |-- 6. k8s_gen.generate()                         namespace/deployment/service/ingress/hpa/serviceaccount, Datadog unified-tagging labels
        |-- 7. terraform_gen.generate()                   ECR repo + IRSA role, S3 backend (bucket/key/table supplied at `terraform init` time)
        |-- 8. workflow_gen.generate()                    .github/workflows/infra-terraform-{app}-{env}.yml + deploy-{app}-{env}.yml
        |
        |-- 9. claude_engine "enhance & review" pass       `claude -p` with cwd=repo, acceptEdits — fixes ports/base image
        |                                                  versions/typos across everything just generated
        |
        |-- 10. git_ops.commit + push
        |
        |-- 11. github_api.create_pull_request()           PR: ticket.branch_name -> base branch
        |
        |-- 12. pr_review.run()                             `claude -p` reviews the diff like a senior reviewer;
        |                                                     if it finds issues, fixes + commits + pushes again (same PR)
        |
        `-- 13. github_api.post_pr_comment()                summary comment linking back to the Jira ticket

PR merged
        |
        v
.github/workflows/infra-terraform-{app}-{env}.yml   (push to main, paths: terraform/**)
        |  OIDC assume-role (vars.GITHUB_OIDC_ROLE_ARN) -> terraform init -backend-config=... (vars.TF_STATE_BUCKET/TF_LOCK_TABLE/AWS_REGION)
        |  -> adopt-if-exists (aws ecr/iam describe + terraform import) -> plan -> apply
        v
.github/workflows/deploy-{app}-{env}.yml            (workflow_run: infra-terraform, conclusion == success)
        |  OIDC assume-role -> re-read terraform outputs -> docker build -> push to ECR
        |  -> aws eks update-kubeconfig (vars.EKS_CLUSTER_NAME) -> sed placeholders -> kubectl apply -> rollout status
        v
App running in the shared EKS cluster for that environment, Datadog-tagged
```

## Naming convention

Every resource this system creates is named `<application-name>-<environment>`
(lowercased, spaces → hyphens), consistently across AWS and Kubernetes:

- ECR repository: `demo-app-dev`
- IAM IRSA role: `demo-app-dev-irsa`
- K8s namespace: `demo-app-dev`
- K8s objects inside that namespace (Deployment/Service/HPA/ServiceAccount/
  Ingress): also `demo-app-dev`

This means `dev`/`staging`/`prod` of the same app never collide on a shared
resource (this bit `orchestrator/templates/terraform/app/main.tf.j2` v1: the
ECR repo name was `var.app_name` alone, so all three environments would have
fought over one repository — fixed to `local.resource_name =
"${var.app_name}-${var.environment}"`). `app_name` alone (no environment) is
still used for the Datadog `service` tag specifically, since Datadog's unified
service tagging treats service/env/version as three separate dimensions, not
one composite name.

## Config lives in GitHub, not in committed files

None of the generated Terraform or GitHub Actions files contain an AWS
account ID, region, cluster name, or role ARN. Instead:

- `pipeline.py` creates a GitHub **Environment** on the app repo named after
  the ticket's `environment` (dev/staging/prod) and seeds it with 6 plain
  (unencrypted) Actions **Variables** — `AWS_REGION`, `EKS_CLUSTER_NAME`,
  `EKS_OIDC_PROVIDER_ARN`, `TF_STATE_BUCKET`, `TF_LOCK_TABLE`,
  `GITHUB_OIDC_ROLE_ARN` — read from that environment's AWS Secrets Manager
  secret.
- The generated workflows reference these as `vars.AWS_REGION` etc., and pass
  them into Terraform two ways: `-backend-config="bucket=${{ vars.TF_STATE_BUCKET }}"`
  (and `region`/`dynamodb_table`) at `terraform init` time, and
  `TF_VAR_aws_region` / `TF_VAR_eks_cluster_name` / `TF_VAR_eks_oidc_provider_arn`
  environment variables for the rest.
- The K8s manifests use string placeholders (`__IMAGE_URI__`, `__IMAGE_TAG__`,
  `__IRSA_ROLE_ARN__`) that `deploy.yml`'s `sed` step fills in from Terraform's
  own outputs at deploy time.

Practically: **you can go to Settings → Environments → dev/staging/prod →
Variables on the app repo and edit any of these six values by hand**, at any
time, without re-running the Jira ticket or touching committed code. The
orchestrator only *seeds* them from Secrets Manager the first time; it doesn't
overwrite a value you've since changed unless you re-provision.

## Idempotency — don't recreate what already exists

`infra-terraform.yml`'s "Adopt pre-existing resources" step runs before
`terraform plan`: it checks (`aws ecr describe-repositories`, `aws iam
get-role`) whether this app+environment's ECR repo / IAM role already exist
and aren't yet in *this* Terraform state, and if so runs `terraform import`
on them instead of letting `apply` fail with "already exists". This covers
re-running a ticket, a state file that got wiped, or a resource someone
created by hand with the same name. `kubectl apply` (used for every K8s
object) is create-or-update by nature, so no equivalent check is needed there.

## Why a shared EKS cluster per environment, not one per app

A ticket-triggered `terraform apply` that creates a *new* EKS control plane
takes 15-20 minutes and costs ~$73/month per cluster before nodes. That doesn't
match "ticket comes in, app gets deployed." Instead:

- `bootstrap-infra/` creates **three** EKS clusters once: `eks-dev`,
  `eks-staging`, `eks-prod` (plus the GitHub OIDC provider, the Terraform state
  S3 bucket + DynamoDB lock table, and the Datadog cluster agent via Helm).
- Every app's per-ticket Terraform (`templates/terraform/app/`) only creates
  what's actually app-specific: an ECR repository, an IRSA IAM role scoped to
  that app's namespace/service account, and the namespace itself — all against
  the *existing* cluster's OIDC provider (looked up via `data` sources).
- This is also what makes "infra pipeline, then deploy pipeline" fast enough to
  run on every merge: the infra apply is a small, idempotent diff, not a
  20-minute cluster build.

If you genuinely need per-app cluster isolation later, swap the `data
"aws_eks_cluster"` lookup in `templates/terraform/app/main.tf.j2` for a real
`module "eks"` call — the rest of the pipeline doesn't change.

## Why templates + Claude, not Claude alone

Dockerfile/K8s/Terraform generation uses deterministic Jinja2 templates first
(reliable, no hallucinated resource names or broken HCL), then a Claude Code
pass reviews and touches up the output (correct Node/Python/Java version pins,
correct exposed port, naming consistency, security nits). The PR-review pass is
where Claude does the most independent judgment — reviewing the full diff and
fixing real issues before a human ever looks at it.

## Trust boundary / OIDC

No long-lived AWS access keys live in GitHub. `bootstrap-infra` creates an IAM
OIDC identity provider for `token.actions.githubusercontent.com` and an IAM
role whose trust policy is scoped to your GitHub org/repos
(`repo:<org>/*:*` or tighter). Both generated workflows assume that role via
`aws-actions/configure-aws-credentials` with `id-token: write` permission —
nothing to rotate.

## Open items / things a v1 intentionally simplifies

- Single Terraform state bucket with per-app/per-env state **keys**
  (`env/<environment>/<app>/terraform.tfstate`), not a bucket per app.
- `language_detect.py` is heuristic (marker files), not an LLM call — kept fast
  and deterministic; Claude's review pass can still override the result if the
  Dockerfile looks wrong for the repo.
- Ingress assumes AWS Load Balancer Controller is already installed on the
  shared clusters (add it to `bootstrap-infra` if it isn't).
- No multi-tenant queueing — the webhook handler processes one ticket at a
  time in a background task. Fine for ticket-driven volume; add a real queue
  (SQS) if this needs to scale.
