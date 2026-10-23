variable "project" {
  type        = string
  description = "Google Cloud project id"
}

variable "region" {
  type    = string
  default = "asia-south1"
}

variable "zone" {
  type    = string
  default = "asia-south1-a"
}

variable "environment" {
  type        = string
  description = "production or staging; part of resource names"
  default     = "production"
}

variable "app_domain" {
  type        = string
  description = "Customer web app host, e.g. app.example.com"
}

variable "staff_domain" {
  type        = string
  description = "Staff web app host, e.g. staff.example.com"
}

variable "staff_members" {
  type        = list(string)
  description = "Who may open the staff app through Identity-Aware Proxy, e.g. [\"group:staff@example.com\"]"
  default     = []
}

variable "github_repository" {
  type        = string
  description = "owner/name of the repository whose Release workflow may deploy (Workload Identity Federation)"
}

variable "machine_type" {
  type    = string
  default = "e2-standard-4"
}

variable "db_tier" {
  type    = string
  default = "db-custom-2-7680"
}

variable "db_high_availability" {
  type        = bool
  description = "Regional (standby in a second zone) instead of zonal"
  default     = true
}

variable "analytics_replica" {
  type        = bool
  description = "Create a read replica for reports and dashboards (set ZK_ANALYTICS_DATABASE_URL to it)"
  default     = false
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "cloud_armor_enabled" {
  type        = bool
  description = "Attach the Cloud Armor policy (OWASP rules, rate limiting) to the load balancer backends"
  default     = true
}

variable "cloud_armor_preview" {
  type        = bool
  description = "Log what Cloud Armor would block without blocking (use for the first days, then turn off)"
  default     = false
}

variable "cloud_armor_sensitivity" {
  type        = number
  description = "Preconfigured WAF sensitivity 1 (fewest false positives) to 4"
  default     = 1
  validation {
    condition     = var.cloud_armor_sensitivity >= 1 && var.cloud_armor_sensitivity <= 4
    error_message = "cloud_armor_sensitivity must be 1, 2, 3 or 4."
  }
}

variable "rate_limit_per_minute" {
  type        = number
  description = "Requests a minute one client address may make before the load balancer answers 429"
  default     = 600
}

variable "files_replica_location" {
  type        = string
  description = "Region (or multi-region) for a copy of the files bucket, e.g. asia-southeast1; empty: no replica"
  default     = ""
}

variable "files_replica_interval_minutes" {
  type        = number
  description = "How often new files are copied to the replica bucket"
  default     = 60
}

variable "files_replica_start_date" {
  type        = string
  description = "First day (YYYY-MM-DD) the replica copy job runs"
  default     = "2026-11-01"
}

variable "db_cross_region_replica_region" {
  type        = string
  description = "Region for a Cloud SQL read replica for disaster recovery, e.g. asia-southeast1; empty: none"
  default     = ""
}

variable "jwt_kms_signing" {
  type        = bool
  description = "Create a Cloud KMS RSA signing key for sign-in tokens (ZK_JWT_SIGNING=rs256, ZK_JWT_KMS_KEY_NAME)"
  default     = false
}
