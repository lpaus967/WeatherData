###################
# CloudWatch Log Groups
# Part of TICKET-016: Set Up CloudWatch Monitoring
###################

# Log group for pipeline orchestration
resource "aws_cloudwatch_log_group" "pipeline" {
  name              = "/weather-pipeline/pipeline"
  retention_in_days = var.log_retention_days

  tags = {
    Name    = "Weather Pipeline Logs"
    Purpose = "Pipeline orchestration logs"
  }
}

# Log group for HRRR download operations
resource "aws_cloudwatch_log_group" "download" {
  name              = "/weather-pipeline/download"
  retention_in_days = var.log_retention_days

  tags = {
    Name    = "HRRR Download Logs"
    Purpose = "Data download operation logs"
  }
}

# Log group for GDAL processing operations
resource "aws_cloudwatch_log_group" "processing" {
  name              = "/weather-pipeline/processing"
  retention_in_days = var.log_retention_days

  tags = {
    Name    = "Processing Logs"
    Purpose = "GRIB2 to COG processing logs"
  }
}

# Log group for tile generation
resource "aws_cloudwatch_log_group" "tiles" {
  name              = "/weather-pipeline/tiles"
  retention_in_days = var.log_retention_days

  tags = {
    Name    = "Tile Generation Logs"
    Purpose = "XYZ tile generation logs"
  }
}

# Log group for S3 operations
resource "aws_cloudwatch_log_group" "s3_upload" {
  name              = "/weather-pipeline/s3-upload"
  retention_in_days = var.log_retention_days

  tags = {
    Name    = "S3 Upload Logs"
    Purpose = "S3 sync and upload logs"
  }
}

###################
# Metric Filters for Error Detection
###################

# Filter for ERROR level logs in pipeline
resource "aws_cloudwatch_log_metric_filter" "pipeline_errors" {
  name           = "PipelineErrors"
  pattern        = "[timestamp, level=ERROR, ...]"
  log_group_name = aws_cloudwatch_log_group.pipeline.name

  metric_transformation {
    name      = "PipelineErrors"
    namespace = "WeatherPipeline"
    value     = "1"
  }
}

# Filter for WARN level logs in pipeline
resource "aws_cloudwatch_log_metric_filter" "pipeline_warnings" {
  name           = "PipelineWarnings"
  pattern        = "[timestamp, level=WARN, ...]"
  log_group_name = aws_cloudwatch_log_group.pipeline.name

  metric_transformation {
    name      = "PipelineWarnings"
    namespace = "WeatherPipeline"
    value     = "1"
  }
}

# Filter for download failures
resource "aws_cloudwatch_log_metric_filter" "download_errors" {
  name           = "DownloadErrors"
  pattern        = "?ERROR ?FAILED ?Exception ?Traceback"
  log_group_name = aws_cloudwatch_log_group.download.name

  metric_transformation {
    name      = "DownloadErrors"
    namespace = "WeatherPipeline"
    value     = "1"
  }
}

# Filter for processing failures
resource "aws_cloudwatch_log_metric_filter" "processing_errors" {
  name           = "ProcessingErrors"
  pattern        = "?ERROR ?FAILED ?Exception ?Traceback"
  log_group_name = aws_cloudwatch_log_group.processing.name

  metric_transformation {
    name      = "ProcessingErrors"
    namespace = "WeatherPipeline"
    value     = "1"
  }
}

# Filter for tile generation failures
resource "aws_cloudwatch_log_metric_filter" "tile_errors" {
  name           = "TileGenerationErrors"
  pattern        = "?ERROR ?FAILED ?Exception ?Traceback"
  log_group_name = aws_cloudwatch_log_group.tiles.name

  metric_transformation {
    name      = "TileGenerationErrors"
    namespace = "WeatherPipeline"
    value     = "1"
  }
}

# Filter for S3 upload failures
resource "aws_cloudwatch_log_metric_filter" "s3_upload_errors" {
  name           = "S3UploadErrors"
  pattern        = "?ERROR ?FAILED ?\"upload failed\""
  log_group_name = aws_cloudwatch_log_group.s3_upload.name

  metric_transformation {
    name      = "S3UploadErrors"
    namespace = "WeatherPipeline"
    value     = "1"
  }
}

# Filter for successful pipeline completions
resource "aws_cloudwatch_log_metric_filter" "pipeline_success" {
  name           = "PipelineSuccess"
  pattern        = "[timestamp, level=SUCCESS, msg=\"Pipeline completed*\"]"
  log_group_name = aws_cloudwatch_log_group.pipeline.name

  metric_transformation {
    name      = "PipelineSuccess"
    namespace = "WeatherPipeline"
    value     = "1"
  }
}

###################
# Outputs
###################

output "log_group_arns" {
  description = "ARNs of created log groups"
  value = {
    pipeline   = aws_cloudwatch_log_group.pipeline.arn
    download   = aws_cloudwatch_log_group.download.arn
    processing = aws_cloudwatch_log_group.processing.arn
    tiles      = aws_cloudwatch_log_group.tiles.arn
    s3_upload  = aws_cloudwatch_log_group.s3_upload.arn
  }
}

output "log_group_names" {
  description = "Names of created log groups"
  value = {
    pipeline   = aws_cloudwatch_log_group.pipeline.name
    download   = aws_cloudwatch_log_group.download.name
    processing = aws_cloudwatch_log_group.processing.name
    tiles      = aws_cloudwatch_log_group.tiles.name
    s3_upload  = aws_cloudwatch_log_group.s3_upload.name
  }
}
