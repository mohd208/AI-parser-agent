variable "aws_region" {
  type        = string
  description = "AWS region for the state bucket, OIDC provider, and (optionally) EKS clusters."
  default     = "us-east-1"
}

variable "github_org" {
  type        = string
  description = "GitHub org (or user) whose repos are allowed to assume the OIDC role. Set github_repo to scope to a single repo instead."
}

variable "github_repo" {
  type        = string
  description = "Optional: restrict the trust policy to a single 'org/repo'. Leave blank to trust every repo in github_org (repo:org/*:*)."
  default     = ""
}

variable "state_bucket_name" {
  type        = string
  description = "Globally-unique S3 bucket name for Terraform remote state."
}

variable "lock_table_name" {
  type    = string
  default = "terraform-locks"
}

variable "create_eks_clusters" {
  type        = bool
  description = "true = create new dev/staging/prod EKS clusters + VPCs here. false = look up existing clusters by name (set existing_cluster_names)."
  default     = false
}

variable "existing_cluster_names" {
  type        = map(string)
  description = "Only used when create_eks_clusters = false. Maps environment -> existing EKS cluster name."
  default = {
    dev     = "eks-dev"
    staging = "eks-staging"
    prod    = "eks-prod"
  }
}

variable "datadog_api_key" {
  type      = string
  sensitive = true
}

variable "install_datadog_agent" {
  type    = bool
  default = true
}
