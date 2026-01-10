# S3-Only Outputs

output "bucket_name" {
  description = "The name of the S3 bucket"
  value       = aws_s3_bucket.weather_data.id
}

output "bucket_arn" {
  description = "The ARN of the S3 bucket"
  value       = aws_s3_bucket.weather_data.arn
}

output "bucket_region" {
  description = "The region where the bucket is deployed"
  value       = aws_s3_bucket.weather_data.region
}

output "bucket_domain_name" {
  description = "The bucket domain name"
  value       = aws_s3_bucket.weather_data.bucket_domain_name
}

output "bucket_regional_domain_name" {
  description = "The bucket regional domain name"
  value       = aws_s3_bucket.weather_data.bucket_regional_domain_name
}

output "example_s3_upload_command" {
  description = "Example AWS CLI command to upload a file"
  value       = "aws s3 cp your-file.tif s3://${aws_s3_bucket.weather_data.id}/processed-cog/temperature/2026-01-09T12Z/f00.tif"
}

output "example_s3_list_command" {
  description = "Example AWS CLI command to list bucket contents"
  value       = "aws s3 ls s3://${aws_s3_bucket.weather_data.id}/ --recursive"
}
