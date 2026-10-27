# Edge protection and cross-region copies of data.
#   * Cloud Armor on both load balancer backends: Google's preconfigured OWASP rules (SQL injection, XSS, local and remote
#     file inclusion, remote code execution, scanners, protocol attacks, session fixation, method enforcement) and a
#     per-client-address rate limit that bans an address for a while when it keeps exceeding it.
#   * The files bucket copied to a bucket in another region (files_replica_location) by Storage Transfer Service.
#   * Optionally a Cloud SQL read replica in another region (db_cross_region_replica_region), promotable in a disaster.

# ---- Cloud Armor ----------------------------------------------------------------------------------------------------
locals {
  # Signed partner webhooks and SCIM carry machine-made bodies that trip generic WAF signatures; they authenticate
  # every request themselves (signature / bearer token) and keep the rate limit.
  waf_exempt_paths = "request.path.startsWith('/v1/payments/webhooks/') || request.path.startsWith('/v1/webhooks/') || request.path.startsWith('/v1/scim/v2/')"
  waf_rules = {
    "sqli-v33-stable"              = 1000
    "xss-v33-stable"               = 1001
    "lfi-v33-stable"               = 1002
    "rfi-v33-stable"               = 1003
    "rce-v33-stable"               = 1004
    "methodenforcement-v33-stable" = 1005
    "scannerdetection-v33-stable"  = 1006
    "protocolattack-v33-stable"    = 1007
    "sessionfixation-v33-stable"   = 1008
  }
}

resource "google_compute_security_policy" "edge" {
  count       = var.cloud_armor_enabled ? 1 : 0
  name        = "${local.name}-edge"
  description = "OWASP preconfigured WAF rules and per-address rate limiting for the Zoikorum load balancer"
  type        = "CLOUD_ARMOR"

  dynamic "rule" {
    for_each = local.waf_rules
    content {
      action      = "deny(403)"
      priority    = rule.value
      preview     = var.cloud_armor_preview
      description = "OWASP ${rule.key}"
      match {
        expr {
          expression = "evaluatePreconfiguredWaf('${rule.key}', {'sensitivity': ${var.cloud_armor_sensitivity}}) && !(${local.waf_exempt_paths})"
        }
      }
    }
  }

  rule {
    action      = "rate_based_ban"
    priority    = 2000
    preview     = var.cloud_armor_preview
    description = "Per client address: more than rate_limit_per_minute requests a minute is refused; repeat offenders are banned"
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    rate_limit_options {
      conform_action   = "allow"
      exceed_action    = "deny(429)"
      enforce_on_key   = "IP"
      ban_duration_sec = 600
      rate_limit_threshold {
        count        = var.rate_limit_per_minute
        interval_sec = 60
      }
      ban_threshold {
        count        = var.rate_limit_per_minute * 5
        interval_sec = 600
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 2147483647
    description = "Default: allow"
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
  }

  depends_on = [google_project_service.apis]
}

# ---- Files bucket replica in another region ----------------------------------------------------------------------------
resource "google_storage_bucket" "files_replica" {
  count                       = var.files_replica_location != "" ? 1 : 0
  name                        = "${var.project}-${local.name}-files-replica"
  location                    = var.files_replica_location
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  versioning { enabled = true }
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 30
      with_state                 = "ARCHIVED"
    }
    action { type = "Delete" }
  }
}

data "google_storage_transfer_project_service_account" "default" {
  count = var.files_replica_location != "" ? 1 : 0
}

resource "google_storage_bucket_iam_member" "transfer_reads_files" {
  for_each = var.files_replica_location != "" ? toset(["roles/storage.objectViewer", "roles/storage.legacyBucketReader"]) : toset([])
  bucket   = google_storage_bucket.files.name
  role     = each.value
  member   = "serviceAccount:${data.google_storage_transfer_project_service_account.default[0].email}"
}

resource "google_storage_bucket_iam_member" "transfer_writes_replica" {
  for_each = var.files_replica_location != "" ? toset(["roles/storage.objectAdmin", "roles/storage.legacyBucketWriter"]) : toset([])
  bucket   = google_storage_bucket.files_replica[0].name
  role     = each.value
  member   = "serviceAccount:${data.google_storage_transfer_project_service_account.default[0].email}"
}

resource "google_storage_transfer_job" "files_replica" {
  count       = var.files_replica_location != "" ? 1 : 0
  description = "${local.name}: copy new files to the replica bucket in ${var.files_replica_location}"
  transfer_spec {
    gcs_data_source { bucket_name = google_storage_bucket.files.name }
    gcs_data_sink { bucket_name = google_storage_bucket.files_replica[0].name }
    transfer_options {
      overwrite_objects_already_existing_in_sink = false # stored files never change; the replica only gains files
      delete_objects_unique_in_sink              = false # a file removed by mistake in the main bucket stays here
    }
  }
  schedule {
    schedule_start_date {
      year  = tonumber(split("-", var.files_replica_start_date)[0])
      month = tonumber(split("-", var.files_replica_start_date)[1])
      day   = tonumber(split("-", var.files_replica_start_date)[2])
    }
    repeat_interval = "${var.files_replica_interval_minutes * 60}s"
  }
  depends_on = [google_storage_bucket_iam_member.transfer_reads_files, google_storage_bucket_iam_member.transfer_writes_replica,
  google_project_service.apis]
}

# ---- Cloud SQL read replica in another region (disaster recovery) ---------------------------------------------------------
resource "google_sql_database_instance" "dr_replica" {
  count                = var.db_cross_region_replica_region != "" ? 1 : 0
  name                 = "${local.name}-dr"
  master_instance_name = google_sql_database_instance.main.name
  database_version     = "POSTGRES_16"
  region               = var.db_cross_region_replica_region
  deletion_protection  = var.deletion_protection
  replica_configuration { failover_target = false } # promoted by hand (DEPLOYMENT.md "Region outage")
  settings {
    tier              = var.db_tier
    availability_type = "ZONAL"
    disk_autoresize   = true
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id # the VPC is global: the replica is reachable from the same network
      ssl_mode        = "ENCRYPTED_ONLY"
    }
  }
}

# ---- Sign-in token signing key in Cloud KMS (ZK_JWT_SIGNING=rs256 with ZK_JWT_KMS_KEY_NAME) -------------------------------
resource "google_kms_crypto_key" "jwt" {
  count    = var.jwt_kms_signing ? 1 : 0
  name     = "jwt-signing"
  key_ring = google_kms_key_ring.zoikorum.id
  purpose  = "ASYMMETRIC_SIGN"
  version_template {
    algorithm = "RSA_SIGN_PKCS1_2048_SHA256"
  }
  lifecycle { prevent_destroy = true }
}

resource "google_kms_crypto_key_iam_member" "vm_jwt" {
  for_each      = var.jwt_kms_signing ? toset(["roles/cloudkms.signerVerifier", "roles/cloudkms.publicKeyViewer"]) : toset([])
  crypto_key_id = google_kms_crypto_key.jwt[0].id
  role          = each.value
  member        = "serviceAccount:${google_service_account.vm.email}"
}
