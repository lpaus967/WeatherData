#!/bin/bash
#
# Weather Data Pipeline Orchestration Script
#
# Automates the complete weather data processing workflow:
# 1. Download HRRR GRIB2 data
# 2. Process GRIB2 to grayscale COGs
# 3. Apply color ramps to COGs
# 4. Generate web map tiles
# 5. Upload to S3
# 6. Generate metadata JSON
# 7. Clean up temporary files
#
# Part of TICKET-010: Create Master Pipeline Orchestration Script
#

set -euo pipefail  # Exit on error, undefined variables, and pipe failures

# ============================================================================
# Configuration
# ============================================================================

# Default configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${LOG_DIR:-/var/log/weather-pipeline}"
WORK_DIR="${WORK_DIR:-/tmp/weather-pipeline}"
S3_BUCKET="${S3_BUCKET:-}"
ENABLE_S3_UPLOAD="${ENABLE_S3_UPLOAD:-false}"
ENABLE_TILES="${ENABLE_TILES:-true}"
DRY_RUN="${DRY_RUN:-false}"
PRIORITY="${PRIORITY:-1}"
ZOOM_LEVELS="${ZOOM_LEVELS:-0-8}"
TILE_PROCESSES="${TILE_PROCESSES:-4}"

# Timestamps
START_TIME=$(date +%s)
DATE_UTC=$(date -u +%Y%m%d)
HOUR_UTC=$(date -u +%H)

# Logging
LOG_FILE="${LOG_DIR}/pipeline_${DATE_UTC}_${HOUR_UTC}00.log"

# ============================================================================
# Functions
# ============================================================================

log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
    echo "[${timestamp}] [${level}] ${message}" | tee -a "$LOG_FILE"
}

log_info() {
    log "INFO" "$@"
}

log_warn() {
    log "WARN" "$@"
}

log_error() {
    log "ERROR" "$@"
}

log_success() {
    log "SUCCESS" "$@"
}

cleanup() {
    local exit_code=$?
    log_info "Cleaning up temporary files..."

    if [[ "$DRY_RUN" == "false" ]]; then
        # Clean up work directory (keep logs)
        # Use sudo if needed because Docker creates files as root
        if [[ -d "$WORK_DIR/downloads" ]]; then
            rm -rf "$WORK_DIR/downloads" 2>/dev/null || sudo rm -rf "$WORK_DIR/downloads"
        fi
        if [[ -d "$WORK_DIR/processed" ]]; then
            rm -rf "$WORK_DIR/processed" 2>/dev/null || sudo rm -rf "$WORK_DIR/processed"
        fi
        if [[ -d "$WORK_DIR/colored" ]]; then
            rm -rf "$WORK_DIR/colored" 2>/dev/null || sudo rm -rf "$WORK_DIR/colored"
        fi
        if [[ -d "$WORK_DIR/tiles" ]]; then
            rm -rf "$WORK_DIR/tiles" 2>/dev/null || sudo rm -rf "$WORK_DIR/tiles"
        fi
    fi

    local end_time=$(date +%s)
    local duration=$((end_time - START_TIME))
    log_info "Pipeline execution time: ${duration}s"

    if [[ $exit_code -eq 0 ]]; then
        log_success "Pipeline completed successfully"
    else
        log_error "Pipeline failed with exit code: $exit_code"
    fi

    exit $exit_code
}

trap cleanup EXIT

check_dependencies() {
    log_info "Checking dependencies..."

    local missing_deps=()

    # Check Docker (required for all processing steps)
    if ! command -v docker &> /dev/null; then
        missing_deps+=("docker")
    fi

    # Check AWS CLI (if S3 upload enabled)
    if [[ "$ENABLE_S3_UPLOAD" == "true" ]] && ! command -v aws &> /dev/null; then
        missing_deps+=("aws-cli")
    fi

    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_error "Missing dependencies: ${missing_deps[*]}"
        return 1
    fi

    log_success "All dependencies found"
    return 0
}

calculate_model_run_time() {
    log_info "Calculating HRRR model run time..."

    # HRRR data is typically available 2-3 hours after model run
    # Use current time - 3 hours for safety
    local current_epoch=$(date -u +%s)
    local three_hours_ago=$((current_epoch - 10800))  # 3 hours = 10800 seconds

    # Use -r for BSD date (macOS) or -d for GNU date (Linux)
    if date -r "$three_hours_ago" +%Y-%m-%d &> /dev/null; then
        # BSD date (macOS)
        MODEL_DATE=$(date -u -r "$three_hours_ago" +%Y-%m-%d)
        MODEL_CYCLE=$(date -u -r "$three_hours_ago" +%H)
    else
        # GNU date (Linux)
        MODEL_DATE=$(date -u -d "@$three_hours_ago" +%Y-%m-%d)
        MODEL_CYCLE=$(date -u -d "@$three_hours_ago" +%H)
    fi

    log_info "Model run: ${MODEL_DATE} cycle ${MODEL_CYCLE}Z"

    export MODEL_DATE
    export MODEL_CYCLE
}

download_data() {
    log_info "==> Step 1: Downloading HRRR data..."

    local download_dir="$WORK_DIR/downloads"
    mkdir -p "$download_dir"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would download HRRR data via Docker"
        # Create dummy file for dry run
        touch "$download_dir/hrrr.${MODEL_DATE}.t${MODEL_CYCLE}z.f00.grib2"
        return 0
    fi

    local cmd="docker run --rm \
        --user $(id -u):$(id -g) \
        -v $download_dir:/data/output \
        -v $PROJECT_ROOT:/app \
        weather-processor:latest \
        python3 /app/scripts/hrrr/download_hrrr.py \
        --date $MODEL_DATE \
        --cycle $MODEL_CYCLE \
        --fxx 0 \
        --variables all \
        --output /data/output \
        --keep-local"

    log_info "Executing: $cmd"

    if $cmd >> "$LOG_FILE" 2>&1; then
        log_success "Download completed"

        # Find downloaded file
        GRIB2_FILE=$(find "$download_dir" -name "*.grib2" | head -1)
        if [[ -z "$GRIB2_FILE" ]]; then
            log_error "No GRIB2 file found after download"
            return 1
        fi

        local file_size=$(du -h "$GRIB2_FILE" | cut -f1)
        log_info "Downloaded: $(basename $GRIB2_FILE) ($file_size)"
        export GRIB2_FILE
        return 0
    else
        log_error "Download failed"
        return 1
    fi
}

process_grib2() {
    log_info "==> Step 2: Processing GRIB2 to COGs..."

    local processed_dir="$WORK_DIR/processed"
    mkdir -p "$processed_dir"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would process GRIB2 to COGs"
        # Create dummy files
        touch "$processed_dir/temperature_2m_hrrr.${MODEL_DATE}.t${MODEL_CYCLE}z.f00.tif"
        touch "$processed_dir/wind_u_10m_hrrr.${MODEL_DATE}.t${MODEL_CYCLE}z.f00.tif"
        return 0
    fi

    local cmd="docker run --rm \
        --user $(id -u):$(id -g) \
        -v $WORK_DIR/downloads:/data/input \
        -v $processed_dir:/data/output \
        -v $PROJECT_ROOT:/app \
        weather-processor:latest \
        python3 /app/scripts/processing/process_weather.py \
        --input /data/input/$(basename $GRIB2_FILE) \
        --output /data/output \
        --priority $PRIORITY"

    log_info "Executing: $cmd"

    if $cmd >> "$LOG_FILE" 2>&1; then
        log_success "GRIB2 processing completed"

        # Count processed files
        local cog_count=$(find "$processed_dir" -name "*.tif" | wc -l)
        log_info "Generated $cog_count COG files"
        export PROCESSED_DIR="$processed_dir"
        return 0
    else
        log_error "GRIB2 processing failed"
        return 1
    fi
}

apply_colormaps() {
    log_info "==> Step 3: Applying color ramps..."

    local colored_dir="$WORK_DIR/colored"
    mkdir -p "$colored_dir"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would apply color ramps to COGs"
        # Create dummy files
        touch "$colored_dir/temperature_2m_hrrr.${MODEL_DATE}.t${MODEL_CYCLE}z.f00_colored.tif"
        return 0
    fi

    local cmd="docker run --rm \
        --user $(id -u):$(id -g) \
        -v $PROCESSED_DIR:/data/input \
        -v $colored_dir:/data/output \
        -v $PROJECT_ROOT:/app \
        weather-processor:latest \
        python3 /app/scripts/processing/apply_colormap.py \
        --input /data/input \
        --output /data/output"

    log_info "Executing: $cmd"

    if $cmd >> "$LOG_FILE" 2>&1; then
        log_success "Color ramp application completed"

        local colored_count=$(find "$colored_dir" -name "*_colored.tif" | wc -l)
        log_info "Generated $colored_count colored COG files"
        export COLORED_DIR="$colored_dir"
        return 0
    else
        log_error "Color ramp application failed"
        return 1
    fi
}

generate_tiles() {
    if [[ "$ENABLE_TILES" != "true" ]]; then
        log_info "==> Step 4: Tile generation disabled (skipped)"
        return 0
    fi

    log_info "==> Step 4: Generating web map tiles..."

    local tiles_dir="$WORK_DIR/tiles"
    mkdir -p "$tiles_dir"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would generate tiles from colored COGs"
        mkdir -p "$tiles_dir/temperature_2m/${MODEL_DATE}T${MODEL_CYCLE}z/00/0/0"
        touch "$tiles_dir/temperature_2m/${MODEL_DATE}T${MODEL_CYCLE}z/00/0/0/0.png"
        return 0
    fi

    local cmd="docker run --rm \
        --user $(id -u):$(id -g) \
        -v $COLORED_DIR:/data/input \
        -v $tiles_dir:/data/output \
        -v $PROJECT_ROOT:/app \
        weather-processor:latest \
        python3 /app/scripts/processing/generate_tiles.py \
        --input /data/input \
        --output /data/output \
        --zoom $ZOOM_LEVELS \
        --processes $TILE_PROCESSES \
        --exclude-transparent \
        --organize"

    log_info "Executing: $cmd"

    if $cmd >> "$LOG_FILE" 2>&1; then
        log_success "Tile generation completed"

        local tile_count=$(find "$tiles_dir" -name "*.png" | wc -l)
        log_info "Generated $tile_count tiles"
        export TILES_DIR="$tiles_dir"
        return 0
    else
        log_error "Tile generation failed"
        return 1
    fi
}

upload_to_s3() {
    if [[ "$ENABLE_S3_UPLOAD" != "true" ]]; then
        log_info "==> Step 5: S3 upload disabled (skipped)"
        return 0
    fi

    if [[ -z "$S3_BUCKET" ]]; then
        log_warn "S3_BUCKET not set, skipping upload"
        return 0
    fi

    log_info "==> Step 5: Uploading to S3..."

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would upload to s3://$S3_BUCKET"
        return 0
    fi

    # Upload colored COGs
    log_info "Uploading colored COGs..."
    if aws s3 sync "$COLORED_DIR" "s3://$S3_BUCKET/colored-cogs/${MODEL_DATE}/" \
        --exclude "*.txt" \
        --quiet >> "$LOG_FILE" 2>&1; then
        log_success "Colored COGs uploaded"
    else
        log_error "Failed to upload colored COGs"
        return 1
    fi

    # Upload tiles (if generated)
    if [[ "$ENABLE_TILES" == "true" ]] && [[ -d "$TILES_DIR" ]]; then
        log_info "Uploading tiles..."
        if aws s3 sync "$TILES_DIR" "s3://$S3_BUCKET/tiles/" \
            --quiet >> "$LOG_FILE" 2>&1; then
            log_success "Tiles uploaded"
        else
            log_error "Failed to upload tiles"
            return 1
        fi
    fi

    return 0
}

generate_metadata() {
    log_info "==> Step 6: Generating metadata..."

    local metadata_file="$WORK_DIR/latest.json"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would generate metadata JSON"
        return 0
    fi

    # Count variables
    local variable_count=$(find "$COLORED_DIR" -name "*_colored.tif" | wc -l)

    # Generate metadata JSON
    cat > "$metadata_file" << EOF
{
  "model": "hrrr",
  "product": "sfc",
  "model_run": {
    "date": "${MODEL_DATE}",
    "cycle": "${MODEL_CYCLE}z",
    "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  },
  "forecast_hours": ["00"],
  "variables": ${variable_count},
  "tiles_enabled": ${ENABLE_TILES},
  "zoom_levels": "${ZOOM_LEVELS}",
  "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "pipeline_version": "1.0",
  "base_url": "https://${S3_BUCKET}.s3.amazonaws.com"
}
EOF

    log_success "Metadata generated: $metadata_file"

    # Upload metadata to S3
    if [[ "$ENABLE_S3_UPLOAD" == "true" ]] && [[ -n "$S3_BUCKET" ]]; then
        log_info "Uploading metadata to S3..."
        if aws s3 cp "$metadata_file" "s3://$S3_BUCKET/metadata/latest.json" \
            --content-type "application/json" \
            --cache-control "max-age=300" \
            --quiet >> "$LOG_FILE" 2>&1; then
            log_success "Metadata uploaded"
        else
            log_warn "Failed to upload metadata"
        fi
    fi

    return 0
}

send_cloudwatch_metrics() {
    if ! command -v aws &> /dev/null; then
        return 0
    fi

    log_info "Sending CloudWatch metrics..."

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would send CloudWatch metrics"
        return 0
    fi

    local duration=$(($(date +%s) - START_TIME))
    local namespace="WeatherPipeline"

    # Send pipeline duration metric
    aws cloudwatch put-metric-data \
        --namespace "$namespace" \
        --metric-name ProcessingTime \
        --value "$duration" \
        --unit Seconds \
        --dimensions Pipeline=HRRR >> "$LOG_FILE" 2>&1 || true

    # Send success metric
    aws cloudwatch put-metric-data \
        --namespace "$namespace" \
        --metric-name Success \
        --value 1 \
        --unit Count \
        --dimensions Pipeline=HRRR >> "$LOG_FILE" 2>&1 || true

    log_info "CloudWatch metrics sent"
}

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Weather Data Pipeline Orchestration Script

OPTIONS:
  --dry-run           Simulate pipeline without executing commands
  --priority N        Processing priority (1-3, default: 1)
  --zoom LEVELS       Zoom levels for tiles (default: 0-8)
  --enable-s3         Enable S3 upload
  --s3-bucket NAME    S3 bucket for uploads
  --disable-tiles     Disable tile generation
  --work-dir PATH     Working directory (default: /tmp/weather-pipeline)
  --log-dir PATH      Log directory (default: /var/log/weather-pipeline)
  --help              Show this help message

EXAMPLES:
  # Dry run (test without execution)
  $0 --dry-run

  # Run with S3 upload
  $0 --enable-s3 --s3-bucket my-weather-bucket

  # Run without tile generation
  $0 --disable-tiles

  # Custom configuration
  $0 --priority 1 --zoom 0-10 --enable-s3 --s3-bucket my-bucket

ENVIRONMENT VARIABLES:
  WORK_DIR            Working directory for temporary files
  LOG_DIR             Directory for log files
  S3_BUCKET           S3 bucket name
  ENABLE_S3_UPLOAD    Enable S3 upload (true/false)
  ENABLE_TILES        Enable tile generation (true/false)
  PRIORITY            Processing priority (1-3)
  ZOOM_LEVELS         Zoom levels for tile generation
  DRY_RUN             Dry run mode (true/false)

EOF
}

# ============================================================================
# Main Pipeline
# ============================================================================

main() {
    # Parse command-line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --priority)
                PRIORITY="$2"
                shift 2
                ;;
            --zoom)
                ZOOM_LEVELS="$2"
                shift 2
                ;;
            --enable-s3)
                ENABLE_S3_UPLOAD=true
                shift
                ;;
            --s3-bucket)
                S3_BUCKET="$2"
                ENABLE_S3_UPLOAD=true
                shift 2
                ;;
            --disable-tiles)
                ENABLE_TILES=false
                shift
                ;;
            --work-dir)
                WORK_DIR="$2"
                shift 2
                ;;
            --log-dir)
                LOG_DIR="$2"
                shift 2
                ;;
            --help)
                usage
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done

    # Create directories
    mkdir -p "$LOG_DIR"
    mkdir -p "$WORK_DIR"

    # Start pipeline
    log_info "=========================================="
    log_info "Weather Data Pipeline Starting"
    log_info "=========================================="
    log_info "Date: $(date -u +%Y-%m-%d)"
    log_info "Time: $(date -u +%H:%M:%S) UTC"
    log_info "Dry Run: $DRY_RUN"
    log_info "Priority: $PRIORITY"
    log_info "Tiles Enabled: $ENABLE_TILES"
    log_info "Zoom Levels: $ZOOM_LEVELS"
    log_info "S3 Upload: $ENABLE_S3_UPLOAD"
    if [[ -n "$S3_BUCKET" ]]; then
        log_info "S3 Bucket: $S3_BUCKET"
    fi
    log_info "Work Directory: $WORK_DIR"
    log_info "Log File: $LOG_FILE"
    log_info "=========================================="

    # Check dependencies
    check_dependencies || exit 1

    # Calculate model run time
    calculate_model_run_time || exit 1

    # Execute pipeline steps
    download_data || exit 1
    process_grib2 || exit 1
    apply_colormaps || exit 1
    generate_tiles || exit 1
    upload_to_s3 || exit 1
    generate_metadata || exit 1

    # Send metrics
    send_cloudwatch_metrics

    log_info "=========================================="
    log_success "Pipeline completed successfully!"
    log_info "=========================================="
}

# Run main function
main "$@"
