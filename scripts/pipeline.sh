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
FORECAST_HOURS="${FORECAST_HOURS:-0-6}"  # Forecast hours to download (e.g., "0-6", "0-12", "0,3,6")

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
        -e HOME=/tmp \
        -e HERBIE_HOME=/data/output \
        -v $download_dir:/data/output \
        -v $PROJECT_ROOT:/app \
        weather-processor:latest \
        python3 /app/scripts/hrrr/download_hrrr.py \
        --date $MODEL_DATE \
        --cycle $MODEL_CYCLE \
        --fxx $FORECAST_HOURS \
        --variables all \
        --output /data/output \
        --keep-local"

    log_info "Executing: $cmd"

    if $cmd >> "$LOG_FILE" 2>&1; then
        log_success "Download completed"

        # Find all downloaded GRIB files
        GRIB2_FILES=($(find "$download_dir" -name "*.grib2" | sort))
        if [[ ${#GRIB2_FILES[@]} -eq 0 ]]; then
            log_error "No GRIB2 files found after download"
            return 1
        fi

        log_info "Downloaded ${#GRIB2_FILES[@]} GRIB2 files:"
        for f in "${GRIB2_FILES[@]}"; do
            local file_size=$(du -h "$f" | cut -f1)
            log_info "  - $(basename $f) ($file_size)"
        done

        export GRIB2_FILES
        export DOWNLOAD_DIR="$download_dir"
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
        # Create dummy files for multiple forecast hours
        for fxx in 00 01 02 03 04 05 06; do
            touch "$processed_dir/temperature_2m_hrrr.${MODEL_DATE}.t${MODEL_CYCLE}z.f${fxx}.tif"
            touch "$processed_dir/wind_u_10m_hrrr.${MODEL_DATE}.t${MODEL_CYCLE}z.f${fxx}.tif"
        done
        return 0
    fi

    # Process each GRIB file
    local processed_count=0
    local total_files=${#GRIB2_FILES[@]}

    for grib_file in "${GRIB2_FILES[@]}"; do
        local grib_name=$(basename "$grib_file")
        processed_count=$((processed_count + 1))
        log_info "Processing GRIB file $processed_count/$total_files: $grib_name"

        local cmd="docker run --rm \
            --user $(id -u):$(id -g) \
            -e HOME=/tmp \
            -v $DOWNLOAD_DIR:/data/input \
            -v $processed_dir:/data/output \
            -v $PROJECT_ROOT:/app \
            weather-processor:latest \
            python3 /app/scripts/processing/process_weather.py \
            --input /data/input/$grib_name \
            --output /data/output \
            --priority $PRIORITY"

        if $cmd >> "$LOG_FILE" 2>&1; then
            log_info "  Processed: $grib_name"
        else
            log_warn "  Failed to process: $grib_name (continuing with remaining files)"
        fi
    done

    log_success "GRIB2 processing completed"

    # Count processed files
    local cog_count=$(find "$processed_dir" -name "*.tif" | wc -l)
    log_info "Generated $cog_count COG files from $total_files GRIB files"
    export PROCESSED_DIR="$processed_dir"
    return 0
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
        -e HOME=/tmp \
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
        -e HOME=/tmp \
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
    local metadata_dir="$WORK_DIR/metadata"
    mkdir -p "$metadata_dir"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would generate metadata JSON"
        return 0
    fi

    # Use Python script to generate comprehensive metadata
    local cmd="docker run --rm \
        --user $(id -u):$(id -g) \
        -e HOME=/tmp \
        -v $TILES_DIR:/data/tiles \
        -v $metadata_dir:/data/output \
        -v $PROJECT_ROOT:/app \
        weather-processor:latest \
        python3 /app/scripts/generate_metadata.py \
        --date $MODEL_DATE \
        --cycle $MODEL_CYCLE \
        --s3-bucket $S3_BUCKET \
        --tiles-dir /data/tiles \
        --config /app/config/variables.yaml \
        --output /data/output/latest.json"

    log_info "Executing metadata generation..."

    if $cmd >> "$LOG_FILE" 2>&1; then
        log_success "Metadata generated"

        # Copy to work dir for upload
        if [[ -f "$metadata_dir/latest.json" ]]; then
            cp "$metadata_dir/latest.json" "$metadata_file"
        fi
    else
        log_warn "Python metadata generation failed, using fallback"
        # Fallback: Generate simple metadata
        local variable_count=$(find "$COLORED_DIR" -name "*_colored.tif" 2>/dev/null | wc -l)
        cat > "$metadata_file" << EOF
{
  "version": "1.0",
  "model": "hrrr",
  "product": "sfc",
  "model_run": {
    "date": "${MODEL_DATE}",
    "cycle": "${MODEL_CYCLE}",
    "cycle_formatted": "${MODEL_CYCLE}Z",
    "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  },
  "forecast_hours": ["00"],
  "variables": [],
  "variable_count": ${variable_count},
  "tiles": {
    "url_template": "https://${S3_BUCKET}.s3.us-east-2.amazonaws.com/tiles/{variable}/{timestamp}/{forecast}/{z}/{x}/{y}.png",
    "format": "png",
    "tile_size": 256
  },
  "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "pipeline_version": "1.0"
}
EOF
        log_info "Fallback metadata generated"
    fi

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

cleanup_old_grib_files() {
    # Clean up old GRIB files from S3, keeping only the most recent model run
    # This prevents storage costs from accumulating with 7+ GRIB files per hour

    if [[ "$ENABLE_S3_UPLOAD" != "true" ]] || [[ -z "$S3_BUCKET" ]]; then
        return 0
    fi

    log_info "Cleaning up old GRIB files from S3..."

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would clean up old GRIB files"
        return 0
    fi

    # Get timestamp for the current run (keep this one)
    local current_run_date="${MODEL_DATE//-/}"  # Remove dashes: 2026-01-11 -> 20260111
    local current_run_pattern="hrrr.${current_run_date}.t${MODEL_CYCLE}z"

    # List all GRIB files and delete anything that doesn't match current run
    log_info "Keeping files matching: $current_run_pattern"

    # List all grib2 files in raw-grib2 prefix
    local grib_files=$(aws s3 ls "s3://$S3_BUCKET/raw-grib2/" --recursive 2>/dev/null | grep "\.grib2$" || true)

    if [[ -z "$grib_files" ]]; then
        log_info "No GRIB files found to clean up"
        return 0
    fi

    local deleted_count=0
    local kept_count=0

    while IFS= read -r line; do
        # Extract the S3 key from ls output
        local s3_key=$(echo "$line" | awk '{print $4}')

        if [[ -z "$s3_key" ]]; then
            continue
        fi

        # Check if this file is from the current run
        if [[ "$s3_key" == *"$current_run_pattern"* ]]; then
            kept_count=$((kept_count + 1))
        else
            # Delete old GRIB file
            if aws s3 rm "s3://$S3_BUCKET/$s3_key" --quiet >> "$LOG_FILE" 2>&1; then
                deleted_count=$((deleted_count + 1))
            fi
        fi
    done <<< "$grib_files"

    log_info "GRIB cleanup complete: kept $kept_count files, deleted $deleted_count old files"
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
  --forecast-hours H  Forecast hours to download (default: 0-6, e.g., "0-12", "0,3,6")
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

  # Run with extended forecast hours (F00-F12)
  $0 --forecast-hours 0-12 --enable-s3 --s3-bucket my-bucket

  # Run without tile generation
  $0 --disable-tiles

  # Custom configuration
  $0 --priority 1 --zoom 0-10 --forecast-hours 0-6 --enable-s3 --s3-bucket my-bucket

ENVIRONMENT VARIABLES:
  WORK_DIR            Working directory for temporary files
  LOG_DIR             Directory for log files
  S3_BUCKET           S3 bucket name
  ENABLE_S3_UPLOAD    Enable S3 upload (true/false)
  ENABLE_TILES        Enable tile generation (true/false)
  PRIORITY            Processing priority (1-3)
  ZOOM_LEVELS         Zoom levels for tile generation
  FORECAST_HOURS      Forecast hours to download (e.g., "0-6", "0-12")
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
            --forecast-hours)
                FORECAST_HOURS="$2"
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
    log_info "Forecast Hours: $FORECAST_HOURS"
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

    # Clean up old GRIB files to reduce S3 storage costs
    cleanup_old_grib_files

    # Send metrics
    send_cloudwatch_metrics

    log_info "=========================================="
    log_success "Pipeline completed successfully!"
    log_info "=========================================="
}

# Run main function
main "$@"
