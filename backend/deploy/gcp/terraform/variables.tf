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
