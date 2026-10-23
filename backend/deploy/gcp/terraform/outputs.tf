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

output "files_replica_bucket" {
  description = "Replica of ZK_GCS_BUCKET in files_replica_location (read it after a region outage)"
  value       = try(google_storage_bucket.files_replica[0].name, null)
}

output "dr_database_private_ip" {
  description = "Host of the cross-region read replica (promote it in a region outage, then point ZK_DATABASE_URL here)"
  value       = try(google_sql_database_instance.dr_replica[0].private_ip_address, null)
}

output "security_policy" {
  description = "Cloud Armor policy attached to the load balancer backends"
  value       = try(google_compute_security_policy.edge[0].name, null)
}

output "jwt_kms_key" {
  description = "ZK_JWT_KMS_KEY_NAME (this key's version 1; a rotated version gets a new number)"
  value       = try("${google_kms_crypto_key.jwt[0].id}/cryptoKeyVersions/1", null)
}
