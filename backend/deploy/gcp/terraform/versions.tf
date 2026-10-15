# Zoikorum on Google Cloud, as code. One state per environment (staging, production):
#   terraform init -backend-config="bucket=<state bucket>" -backend-config="prefix=zoikorum/production"
#   terraform plan -var-file=production.tfvars
# See backend/docs/DEPLOYMENT.md ("Google Cloud setup").
terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.8"
    }
  }
  backend "gcs" {}
}

provider "google" {
  project = var.project
  region  = var.region
}
