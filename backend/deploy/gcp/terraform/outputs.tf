# Values for GitHub repository variables and Secret Manager (none of them is secret).
output "load_balancer_ip" {
  description = "Point app_domain and staff_domain here (DNS A records); also the ZK_LB_IP setting"
  value       = google_compute_global_address.lb.address
}

output "registry" {
  description = "GCP_REGISTRY"
  value       = "${var.region}-docker.pkg.dev/${var.project}/${google_artifact_registry_repository.images.repository_id}"
}

output "vm" {
  description = "GCP_VM and GCP_ZONE"
  value       = { name = google_compute_instance.app.name, zone = var.zone }
}

output "deploy_service_account" {
  description = "GCP_DEPLOY_SA"
  value       = google_service_account.deploy.email
}

output "workload_identity_provider" {
  description = "GCP_WIF_PROVIDER"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "database_private_ip" {
  description = "Host for ZK_DATABASE_URL"
  value       = google_sql_database_instance.main.private_ip_address
}

output "analytics_private_ip" {
  description = "Host for ZK_ANALYTICS_DATABASE_URL (when analytics_replica = true)"
  value       = try(google_sql_database_instance.analytics[0].private_ip_address, null)
}

output "files_bucket" {
  description = "ZK_GCS_BUCKET"
  value       = google_storage_bucket.files.name
}

output "field_kms_key" {
  description = "ZK_FIELD_KMS_KEY_NAME"
  value       = google_kms_crypto_key.fields.id
}
