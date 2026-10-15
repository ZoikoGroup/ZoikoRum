locals {
  name = "zoikorum-${var.environment}"
  # Secret Manager names follow secrets.list: ZK_JWT_SECRET -> zk-jwt-secret. Only the secrets are created here; their
  # values are added by hand (gcloud secrets versions add), so no value ever appears in Terraform state.
  secret_names = toset([
    for line in split("\n", file("${path.module}/../secrets.list")) :
    lower(replace(trimspace(line), "_", "-")) if trimspace(line) != "" && !startswith(trimspace(line), "#")
  ])
  services = [
    "artifactregistry.googleapis.com", "cloudkms.googleapis.com", "compute.googleapis.com", "iam.googleapis.com",
    "iamcredentials.googleapis.com", "iap.googleapis.com", "secretmanager.googleapis.com", "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com", "storage.googleapis.com", "sts.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

# ---- Identities ---------------------------------------------------------------------------------------------------
resource "google_service_account" "vm" {
  account_id   = "${local.name}-vm"
  display_name = "Zoikorum ${var.environment} VM (API, worker)"
}

resource "google_service_account" "deploy" {
  account_id   = "${local.name}-deploy"
  display_name = "Zoikorum ${var.environment} releases (GitHub Actions)"
}

resource "google_project_iam_member" "vm_roles" {
  for_each = toset(["roles/logging.logWriter", "roles/monitoring.metricWriter", "roles/cloudsql.client", "roles/artifactregistry.reader"])
  project  = var.project
  role     = each.value
  member   = "serviceAccount:${google_service_account.vm.email}"
}

resource "google_project_iam_member" "deploy_roles" {
  for_each = toset(["roles/artifactregistry.writer", "roles/compute.instanceAdmin.v1", "roles/iap.tunnelResourceAccessor"])
  project  = var.project
  role     = each.value
  member   = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_service_account_iam_member" "deploy_acts_as_vm" { # SSH to a VM that runs as the VM account
  service_account_id = google_service_account.vm.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy.email}"
}

# GitHub signs in without a stored key: only the Release workflow of this repository may act as the deploy account.
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "${local.name}-github"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.workflow"   = "assertion.workflow"
  }
  attribute_condition = "assertion.repository == \"${var.github_repository}\" && assertion.workflow == \"Release\""
  oidc { issuer_uri = "https://token.actions.githubusercontent.com" }
}

resource "google_service_account_iam_member" "github_deploy" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

# ---- Images, keys, secrets, files ---------------------------------------------------------------------------------
resource "google_artifact_registry_repository" "images" {
  repository_id = "zoikorum"
  location      = var.region
  format        = "DOCKER"
  cleanup_policies { # keep the last 20 releases of each image (rollback range)
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions { keep_count = 20 }
  }
  depends_on = [google_project_service.apis]
}

resource "google_kms_key_ring" "zoikorum" {
  name       = local.name
  location   = var.region
  depends_on = [google_project_service.apis]
}

resource "google_kms_crypto_key" "fields" { # wraps the field-encryption data keys (ZK_FIELD_KMS_KEY_NAME)
  name            = "fields"
  key_ring        = google_kms_key_ring.zoikorum.id
  rotation_period = "31536000s"
  lifecycle { prevent_destroy = true }
}

resource "google_kms_crypto_key_iam_member" "vm_fields" {
  crypto_key_id = google_kms_crypto_key.fields.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.vm.email}"
}

resource "google_secret_manager_secret" "settings" {
  for_each  = local.secret_names
  secret_id = each.value
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "vm_reads_settings" {
  for_each  = google_secret_manager_secret.settings
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.vm.email}"
}

resource "google_storage_bucket" "files" { # ZK_GCS_BUCKET
  name                        = "${var.project}-${local.name}-files"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  versioning { enabled = true }
  lifecycle_rule { # old versions of replaced files: removed after 30 days
    condition {
      days_since_noncurrent_time = 30
      with_state                 = "ARCHIVED"
    }
    action { type = "Delete" }
  }
}

resource "google_storage_bucket_iam_member" "vm_files" {
  for_each = toset(["roles/storage.objectAdmin", "roles/storage.legacyBucketReader"])
  bucket   = google_storage_bucket.files.name
  role     = each.value
  member   = "serviceAccount:${google_service_account.vm.email}"
}

# ---- Network and database -----------------------------------------------------------------------------------------
resource "google_compute_network" "vpc" {
  name                    = local.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "app" {
  name                     = "${local.name}-app"
  network                  = google_compute_network.vpc.id
  region                   = var.region
  ip_cidr_range            = "10.20.0.0/24"
  private_ip_google_access = true
}

resource "google_compute_router" "router" {
  name    = local.name
  network = google_compute_network.vpc.id
  region  = var.region
}

resource "google_compute_router_nat" "nat" { # outbound only (email, payments, registry); the VM has no public address
  name                               = local.name
  router                             = google_compute_router.router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_global_address" "sql_range" {
  name          = "${local.name}-sql"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "sql" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql_range.name]
}

resource "google_sql_database_instance" "main" {
  name                = local.name
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = var.deletion_protection
  settings {
    tier              = var.db_tier
    availability_type = var.db_high_availability ? "REGIONAL" : "ZONAL"
    disk_autoresize   = true
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "20:30" # 02:00 India time
      transaction_log_retention_days = 7
      backup_retention_settings { retained_backups = 30 }
    }
    maintenance_window {
      day  = 7
      hour = 21
    }
    insights_config { query_insights_enabled = true }
  }
  depends_on = [google_service_networking_connection.sql]
}

resource "google_sql_database" "zoikorum" {
  name     = "zoikorum"
  instance = google_sql_database_instance.main.name
}

resource "google_sql_database_instance" "analytics" { # reports and dashboards (ZK_ANALYTICS_DATABASE_URL)
  count                = var.analytics_replica ? 1 : 0
  name                 = "${local.name}-analytics"
  master_instance_name = google_sql_database_instance.main.name
  database_version     = "POSTGRES_16"
  region               = var.region
  deletion_protection  = var.deletion_protection
  replica_configuration { failover_target = false }
  settings {
    tier              = var.db_tier
    availability_type = "ZONAL"
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }
  }
}
# Database users (owner zoikorum_migrate, application zoikorum_app) are created by hand with their passwords, as in
# DEPLOYMENT.md "Database users", so no password is kept in Terraform state.

# ---- The VM -------------------------------------------------------------------------------------------------------
resource "google_compute_instance" "app" {
  name         = local.name
  zone         = var.zone
  machine_type = var.machine_type
  tags         = ["zoikorum-web"]
  boot_disk {
    initialize_params {
      image = "cos-cloud/cos-stable"
      size  = 50
    }
  }
  network_interface {
    subnetwork = google_compute_subnetwork.app.id # no public address: outbound through Cloud NAT, inbound through the load balancer
  }
  service_account {
    email  = google_service_account.vm.email
    scopes = ["cloud-platform"]
  }
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  metadata                  = { enable-oslogin = "TRUE" }
  allow_stopping_for_update = true
}

resource "google_compute_firewall" "lb" { # only Google's load balancer and health checks reach the web ports
  name          = "${local.name}-lb"
  network       = google_compute_network.vpc.id
  source_ranges = ["35.191.0.0/16", "130.211.0.0/22"]
  target_tags   = ["zoikorum-web"]
  allow {
    protocol = "tcp"
    ports    = ["8080", "8081"]
  }
}

resource "google_compute_firewall" "iap_ssh" { # SSH only through Identity-Aware Proxy
  name          = "${local.name}-iap-ssh"
  network       = google_compute_network.vpc.id
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["zoikorum-web"]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_instance_group" "app" {
  name      = local.name
  zone      = var.zone
  instances = [google_compute_instance.app.self_link]
  named_port {
    name = "web"
    port = 8080
  }
  named_port {
    name = "staff"
    port = 8081
  }
}

# ---- HTTPS load balancer ------------------------------------------------------------------------------------------
resource "google_compute_health_check" "web" {
  for_each = { web = 8080, staff = 8081 }
  name     = "${local.name}-${each.key}"
  http_health_check {
    port         = each.value
    request_path = "/ready"
  }
}

resource "google_compute_backend_service" "web" {
  for_each              = { web = "web", staff = "staff" }
  name                  = "${local.name}-${each.key}"
  protocol              = "HTTP"
  port_name             = each.value
  load_balancing_scheme = "EXTERNAL_MANAGED"
  timeout_sec           = 60
  health_checks         = [google_compute_health_check.web[each.key].id]
  backend { group = google_compute_instance_group.app.self_link }
  log_config { enable = true }
  dynamic "iap" { # the staff app: only the accounts in staff_members get through
    for_each = each.key == "staff" ? [1] : []
    content { enabled = true }
  }
}

resource "google_iap_web_backend_service_iam_member" "staff" {
  for_each            = toset(var.staff_members)
  web_backend_service = google_compute_backend_service.web["staff"].name
  role                = "roles/iap.httpsResourceAccessor"
  member              = each.value
}

resource "google_compute_url_map" "https" {
  name            = local.name
  default_service = google_compute_backend_service.web["web"].id
  host_rule {
    hosts        = [var.app_domain]
    path_matcher = "web"
  }
  host_rule {
    hosts        = [var.staff_domain]
    path_matcher = "staff"
  }
  path_matcher {
    name            = "web"
    default_service = google_compute_backend_service.web["web"].id
  }
  path_matcher {
    name            = "staff"
    default_service = google_compute_backend_service.web["staff"].id
  }
}

resource "google_compute_managed_ssl_certificate" "web" {
  name = local.name
  managed { domains = [var.app_domain, var.staff_domain] }
}

resource "google_compute_target_https_proxy" "https" {
  name             = local.name
  url_map          = google_compute_url_map.https.id
  ssl_certificates = [google_compute_managed_ssl_certificate.web.id]
}

resource "google_compute_global_address" "lb" {
  name = local.name
}

resource "google_compute_global_forwarding_rule" "https" {
  name                  = "${local.name}-https"
  target                = google_compute_target_https_proxy.https.id
  ip_address            = google_compute_global_address.lb.address
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

resource "google_compute_url_map" "redirect" { # http:// -> https://
  name = "${local.name}-redirect"
  default_url_redirect {
    https_redirect = true
    strip_query    = false
  }
}

resource "google_compute_target_http_proxy" "redirect" {
  name    = "${local.name}-redirect"
  url_map = google_compute_url_map.redirect.id
}

resource "google_compute_global_forwarding_rule" "http" {
  name                  = "${local.name}-http"
  target                = google_compute_target_http_proxy.redirect.id
  ip_address            = google_compute_global_address.lb.address
  port_range            = "80"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}
