# S3-Only Configuration (for users without IAM permissions)
# This file configures only S3 resources that can be managed with S3-only AWS credentials

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = var.project_tags
  }
}

###################
# S3 Bucket
###################

resource "aws_s3_bucket" "weather_data" {
  bucket = var.bucket_name

  tags = {
    Name        = "Weather Data Bucket"
    Environment = var.environment
    Purpose     = "Store HRRR weather forecast data and processed tiles"
  }
}

# Block public access
resource "aws_s3_bucket_public_access_block" "weather_data_pab" {
  bucket = aws_s3_bucket.weather_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Enable versioning
resource "aws_s3_bucket_versioning" "weather_data_versioning" {
  bucket = aws_s3_bucket.weather_data.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Server-side encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "weather_data_encryption" {
  bucket = aws_s3_bucket.weather_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# CORS configuration
resource "aws_s3_bucket_cors_configuration" "weather_data_cors" {
  bucket = aws_s3_bucket.weather_data.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag", "Content-Length"]
    max_age_seconds = 3000
  }
}
