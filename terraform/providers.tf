terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.46"
    }
  }

  # Keep the backend partial so CI or operators can inject real values without
  # hard-coding state storage details in the repository.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region
}
