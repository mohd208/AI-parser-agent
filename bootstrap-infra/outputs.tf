output "tf_state_bucket" {
  value = aws_s3_bucket.tf_state.bucket
}

output "tf_lock_table" {
  value = aws_dynamodb_table.tf_lock.name
}

output "github_oidc_role_arn" {
  value = aws_iam_role.github_actions.arn
}

output "eks_oidc_provider_arns" {
  description = "Per-environment cluster OIDC provider ARN - copy the value for each env into that env's Secrets Manager secret as EKS_OIDC_PROVIDER_ARN (used by the per-app IRSA role's trust policy)."
  value       = local.eks_oidc_provider_arns
}

output "cluster_names" {
  description = "Copy into each env's secret as EKS_CLUSTER_NAME."
  value       = local.cluster_names
}
