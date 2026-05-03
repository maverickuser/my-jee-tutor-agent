terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.46"
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = "~> 1.78"
    }
  }

  # Keep the backend partial so CI or operators can inject real values without
  # hard-coding state storage details in the repository.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region
}

provider "awscc" {
  region = var.aws_region
}
