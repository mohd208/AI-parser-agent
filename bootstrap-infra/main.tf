terraform {
  required_version = ">= 1.7"
  required_providers {
    aws        = { source = "hashicorp/aws", version = "~> 5.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.31" }
    helm       = { source = "hashicorp/helm", version = "~> 2.14" }
    tls        = { source = "hashicorp/tls", version = "~> 4.0" }
  }

  # Bootstrap chicken-and-egg: this stack creates the S3 bucket everything
  # else uses as a backend, so its own state stays local (or point this at a
  # bucket you created by hand once). See docs/SETUP.md step 3.
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# 1. Terraform remote state: S3 bucket + DynamoDB lock table, shared by every
#    per-app terraform module (each app gets its own state *key*, see
#    orchestrator/templates/terraform/app/backend.tf.j2).
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "tf_state" {
  bucket = var.state_bucket_name
}

resource "aws_s3_bucket_versioning" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "tf_state" {
  bucket                  = aws_s3_bucket.tf_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "tf_lock" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
}

# ---------------------------------------------------------------------------
# 2. GitHub OIDC provider + role that every generated Actions workflow
#    (infra-terraform.yml / deploy.yml) assumes via
#    aws-actions/configure-aws-credentials. No static AWS keys in GitHub.
# ---------------------------------------------------------------------------

data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]
}

locals {
  github_subject = var.github_repo != "" ? "repo:${var.github_repo}:*" : "repo:${var.github_org}/*:*"
}

data "aws_iam_policy_document" "github_actions_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.github_subject]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "github-actions-devops-agent"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json
}

# Scoped to exactly what the generated workflows do: manage this app's ECR
# repo + IRSA role via Terraform (via the app's own state), push images, and
# deploy to the shared EKS cluster. Tighten resource ARNs further once you
# know your naming convention.
data "aws_iam_policy_document" "github_actions_permissions" {
  statement {
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchCheckLayerAvailability",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:CreateRepository",
      "ecr:DescribeRepositories",
      "ecr:PutLifecyclePolicy",
    ]
    resources = ["*"]
  }
  statement {
    effect    = "Allow"
    actions   = ["eks:DescribeCluster"]
    resources = ["*"]
  }
  statement {
    effect = "Allow"
    actions = [
      "iam:CreateRole", "iam:GetRole", "iam:DeleteRole",
      "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy",
      "iam:TagRole", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
    ]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*-irsa"]
  }
  statement {
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.tf_state.arn, "${aws_s3_bucket.tf_state.arn}/*"]
  }
  statement {
    effect    = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.tf_lock.arn]
  }
}

resource "aws_iam_role_policy" "github_actions" {
  name   = "devops-agent-permissions"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_permissions.json
}

# ---------------------------------------------------------------------------
# 3. EKS clusters - one per environment, SHARED across every app (see
#    docs/ARCHITECTURE.md for why). Default is to look up clusters you
#    already run; flip create_eks_clusters = true to have this stack create
#    them (VPC + terraform-aws-modules/eks/aws), which takes ~15-20 min once.
# ---------------------------------------------------------------------------

module "eks_dev" {
  count   = var.create_eks_clusters ? 1 : 0
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = "eks-dev"
  cluster_version = "1.30"
  vpc_id          = module.vpc_dev[0].vpc_id
  subnet_ids      = module.vpc_dev[0].private_subnets

  enable_irsa = true # creates this cluster's own IAM OIDC provider, used by every app's IRSA role

  eks_managed_node_groups = {
    default = { min_size = 1, max_size = 4, desired_size = 2, instance_types = ["t3.medium"] }
  }
}

module "vpc_dev" {
  count   = var.create_eks_clusters ? 1 : 0
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name               = "eks-dev-vpc"
  cidr               = "10.10.0.0/16"
  azs                = ["${var.aws_region}a", "${var.aws_region}b"]
  private_subnets    = ["10.10.1.0/24", "10.10.2.0/24"]
  public_subnets     = ["10.10.101.0/24", "10.10.102.0/24"]
  enable_nat_gateway = true
  single_nat_gateway = true
}

# staging/prod follow the same module pattern as dev - duplicate
# module.eks_dev / module.vpc_dev above with staging/prod names and distinct
# CIDRs (10.20.0.0/16, 10.30.0.0/16) once you're ready to have this stack own
# cluster creation instead of importing existing clusters.

data "aws_eks_cluster" "existing" {
  for_each = var.create_eks_clusters ? {} : var.existing_cluster_names
  name     = each.value
}

# Existing clusters must already have IRSA enabled (an IAM OIDC provider
# registered for their issuer URL) - true for any cluster created with
# `eksctl` or the terraform-aws-modules/eks module with enable_irsa = true.
# If yours doesn't, register one: aws iam create-open-id-connect-provider.
data "aws_iam_openid_connect_provider" "existing" {
  for_each = var.create_eks_clusters ? {} : var.existing_cluster_names
  url      = data.aws_eks_cluster.existing[each.key].identity[0].oidc[0].issuer
}

locals {
  cluster_names = var.create_eks_clusters ? {
    dev = module.eks_dev[0].cluster_name
    # staging = module.eks_staging[0].cluster_name
    # prod    = module.eks_prod[0].cluster_name
  } : var.existing_cluster_names

  # This is what gets copied into each of the 3 Secrets Manager secrets as
  # EKS_OIDC_PROVIDER_ARN - it is the CLUSTER's OIDC provider (for pod IRSA
  # roles), not the GitHub Actions OIDC provider defined above.
  eks_oidc_provider_arns = var.create_eks_clusters ? {
    dev = module.eks_dev[0].oidc_provider_arn
  } : { for env, prov in data.aws_iam_openid_connect_provider.existing : env => prov.arn }
}

# ---------------------------------------------------------------------------
# 4. Datadog cluster agent (DaemonSet + cluster agent) on each environment's
#    cluster, so every app's pods get picked up for K8s monitoring the
#    moment they're deployed - no per-app Datadog install step needed.
# ---------------------------------------------------------------------------

provider "kubernetes" {
  alias                  = "dev"
  host                   = var.create_eks_clusters ? module.eks_dev[0].cluster_endpoint : data.aws_eks_cluster.existing["dev"].endpoint
  cluster_ca_certificate = base64decode(var.create_eks_clusters ? module.eks_dev[0].cluster_certificate_authority_data : data.aws_eks_cluster.existing["dev"].certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.dev.token
}

data "aws_eks_cluster_auth" "dev" {
  name = local.cluster_names["dev"]
}

provider "helm" {
  alias = "dev"
  kubernetes {
    host                   = var.create_eks_clusters ? module.eks_dev[0].cluster_endpoint : data.aws_eks_cluster.existing["dev"].endpoint
    cluster_ca_certificate = base64decode(var.create_eks_clusters ? module.eks_dev[0].cluster_certificate_authority_data : data.aws_eks_cluster.existing["dev"].certificate_authority[0].data)
    token                  = data.aws_eks_cluster_auth.dev.token
  }
}

resource "kubernetes_secret" "datadog_dev" {
  provider = kubernetes.dev
  count    = var.install_datadog_agent ? 1 : 0
  metadata {
    name      = "datadog-secret"
    namespace = "default"
  }
  data = { "api-key" = var.datadog_api_key }
}

resource "helm_release" "datadog_dev" {
  provider   = helm.dev
  count      = var.install_datadog_agent ? 1 : 0
  name       = "datadog"
  repository = "https://helm.datadoghq.com"
  chart      = "datadog"
  namespace  = "default"

  set {
    name  = "datadog.apiKeyExistingSecret"
    value = kubernetes_secret.datadog_dev[0].metadata[0].name
  }
  set {
    name  = "datadog.kubelet.tlsVerify"
    value = "false"
  }
  set {
    name  = "clusterAgent.enabled"
    value = "true"
  }
  set {
    name  = "datadog.env[0].name"
    value = "DD_ENV"
  }
  set {
    name  = "datadog.env[0].value"
    value = "dev"
  }
}

# Repeat the dev provider/helm_release block above for staging and prod
# (provider aliases "staging"/"prod", cluster_names["staging"|"prod"]) once
# those clusters exist - kept to one environment here to keep this file
# readable; it's a straight copy-paste with the env swapped.
