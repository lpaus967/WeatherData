# Asana Task Structure for Weather Data Pipeline

## Parent Task

**Weather Data Pipeline - Automated Infrastructure**
_Status: In Progress | Priority: P0 | Timeline: ~2.5-3 weeks | **3/25 tickets complete**_

---

## Phase 1: Infrastructure Setup

**Section** (or sub-project in Asana)

### TICKET-001: Set Up AWS Infrastructure with Terraform

- **Priority**: P0 | **Effort**: M (4-8 hours) | **Status**: 🟢 Complete
- **Sub-tasks**:
  - [x] Update `main.tf` to create organized S3 bucket structure (raw-grib2/, processed-cog/, tiles/, metadata/)
  - [x] Create S3 lifecycle policies for automated data retention
    - raw-grib2: Delete after 7 days
    - processed-cog: Transition to Standard-IA after 30 days, delete after 60 days
    - tiles: Delete after 3 days
    - metadata: Never expire (versions after 30 days)
  - [x] Create IAM role for EC2 instance with S3 read/write permissions (manual via Console)
  - [x] Create IAM policy for CloudWatch metrics and logs (manual via Console)
  - [ ] Add CloudFront distribution (optional for CDN) - Skipped for now
  - [x] Configure CORS for S3 bucket to allow web access
  - [x] Add versioning for processed-cog bucket (for rollback capability)
- **Acceptance**: ✅ `terraform apply` succeeded, S3 bucket `sat-data-automation-test` configured, lifecycle policies active
- **Completion Date**: 2026-01-10
- **Documentation**: `terraform/TICKET-001-COMPLETE.md`

### TICKET-002: Provision EC2 Instance for Data Processing

- **Priority**: P0 | **Effort**: S (<4 hours) | **Status**: 🟢 Complete
- **Sub-tasks**:
  - [x] Launch EC2 instance in us-east-2 (same region as S3)
  - [x] Configure security group (Session Manager connection)
  - [x] Attach IAM role with S3 and CloudWatch permissions
  - [x] Install system dependencies:
    - [x] Docker 29.1.4 ✅
    - [x] AWS CLI v2.32.32 ✅
    - [x] Python 3.12.3 ✅
    - [x] pip, git ✅
  - [x] Configure AWS CLI with IAM role (automatic)
  - [x] Set up CloudWatch Logs agent
  - [x] Create working directory: `/home/ubuntu/weather-pipeline/`
  - [x] Verify S3 access to `sat-data-automation-test`
  - [x] Verify Docker permissions (no sudo required)
  - [x] Clone repository to EC2
  - [x] Build Docker image on EC2: `weather-processor:latest`
  - [x] Test Herbie functionality
- **Acceptance**: ✅ Can connect via Session Manager, Docker 29.1.4 running, AWS CLI configured, S3 access verified, 45 GB free disk space
- **Completion Date**: 2026-01-10
- **Documentation**: `terraform/TICKET-002-COMPLETE.md`

### TICKET-003: Create Docker Container for Weather Data Processing

- **Priority**: P0 | **Effort**: M (4-8 hours) | **Status**: 🟢 Complete
- **Sub-tasks**:
  - [x] Create `docker/Dockerfile` based on `osgeo/gdal:ubuntu-small-3.8.0`
  - [x] Install Python dependencies (herbie-data, rioxarray, xarray, boto3, pyyaml)
  - [x] Create `docker/requirements.txt`
  - [x] Install cfgrib and eccodes for GRIB2 support (required by Herbie)
  - [x] Add processing scripts to container (ready for TICKET-004)
  - [x] Test download and processing workflow locally
  - [x] Build and tag image: `weather-processor:latest`
  - [x] Test container with sample HRRR download on EC2 ✅
  - [x] Document resource requirements (memory, CPU)
  - [x] Fixed NumPy compatibility issue (pinned to 1.x for GDAL)
- **Acceptance**: ✅ Docker image built (2.35GB with all dependencies), Herbie working, S3 access verified, all 6 tests passing
- **Completion Date**: 2026-01-10
- **Documentation**: `docker/BUILD_SUMMARY.md`

---

## Phase 2: Data Ingestion Scripts

**Section** (or sub-project in Asana)

### TICKET-004: Create HRRR Download Script with Herbie

- **Priority**: P0 | **Effort**: M (4-8 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create `scripts/download_hrrr.py` using Herbie
  - [ ] Install herbie-data package in Docker container
  - [ ] Download forecast hours F00-F12 for specified variables
  - [ ] Use Herbie's smart download for specific variables (TMP:2 m, UGRD:10 m, VGRD:10 m)
  - [ ] Save downloaded data as NetCDF or retain GRIB2 format
  - [ ] Upload processed data to S3 with timestamped paths
  - [ ] Add logging with timestamps
  - [ ] Handle missing or delayed NOAA data gracefully (Herbie auto-fallback)
  - [ ] Add command-line arguments (--date, --cycle, --forecast-hours, --variables)
  - [ ] Create unit tests
- **Acceptance**: Can download all 13 forecast hours, handles network errors, completes in <5 minutes

### TICKET-005: Create Variable Configuration System

- **Priority**: P1 | **Effort**: XS (<2 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create `config/variables.yaml` configuration file
  - [ ] Define variable mappings with Herbie search strings
  - [ ] Include visualization settings (color ramps, units, display names)
  - [ ] Add metadata for each variable (description, units, typical range)
  - [ ] Create helper script to list available variables from a model
  - [ ] Validate configuration on startup
- **Acceptance**: Configuration file is valid YAML, helper script can query available variables, easy to add new variables

---

## Phase 3: GDAL Processing Pipeline

**Section** (or sub-project in Asana)

### TICKET-006: Create Data Processing Script with rioxarray

- **Priority**: P0 | **Effort**: M (4-8 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create `scripts/process_weather.py`
  - [ ] Load NetCDF files from Herbie downloads into xarray
  - [ ] Implement data processing function:
    - [ ] Reproject to EPSG:3857 (Web Mercator) using rioxarray
    - [ ] Apply unit conversions (Kelvin to Celsius, etc.)
    - [ ] Apply bilinear resampling
    - [ ] Export to Cloud Optimized GeoTIFF (COG)
    - [ ] Apply DEFLATE compression
    - [ ] Add overviews for multi-scale viewing
  - [ ] Implement parallel processing for multiple forecast hours
  - [ ] Use ProcessPoolExecutor or dask for multi-core utilization
  - [ ] Add progress tracking and logging
  - [ ] Handle processing errors gracefully
  - [ ] Validate output COG files
  - [ ] Add command-line arguments (--input-dir, --output-dir, --variable)
  - [ ] Optimize for web serving (tile-aligned blocks)
- **Acceptance**: Processes single NetCDF to COG successfully, output <5MB, processes 13 files in <10 minutes

### TICKET-007: Add Color Ramp and Visualization Styling

- **Priority**: P1 | **Effort**: M (4-8 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create color ramp configuration file (JSON)
  - [ ] Define temperature ranges and colors (e.g., -40°C to 50°C)
  - [ ] Implement `gdaldem color-relief` in processing pipeline
  - [ ] Convert to 8-bit RGB with transparency
  - [ ] Generate PNG tiles for web serving
  - [ ] Create multiple color schemes (temperature, precipitation, wind)
  - [ ] Add command-line option to select color scheme
  - [ ] Document color ramp customization
- **Acceptance**: Output files have color applied, temperature ranges map to intuitive colors, file sizes reduced

---

## Phase 4: Tile Generation

**Section** (or sub-project in Asana)

### TICKET-008: Implement Tile Generation Strategy

- **Priority**: P1 | **Effort**: M (4-8 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] **Option A: Pre-generated Tiles**
    - [ ] Create `scripts/generate_tiles.py` wrapper for gdal2tiles
    - [ ] Generate zoom levels 1-10
    - [ ] Use XYZ tile naming convention
    - [ ] Output PNG tiles with transparency
    - [ ] Implement parallel tile generation
    - [ ] Create directory structure: `{variable}/{timestamp}/f{hour}/{z}/{x}/{y}.png`
  - [ ] **Option B: Dynamic TiTiler (Recommended)**
    - [ ] Deploy TiTiler on ECS Fargate
    - [ ] Configure TiTiler to read COGs from S3
    - [ ] Set up Application Load Balancer
    - [ ] Configure caching headers
    - [ ] Document tile URL format
  - [ ] Benchmark both approaches (speed, storage, cost)
  - [ ] Document pros/cons of each approach
- **Acceptance**: Tiles render correctly in Mapbox, zoom levels 1-10 available, tiles load in <500ms

### TICKET-009: Optimize Tile Generation Performance

- **Priority**: P2 | **Effort**: M (4-8 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Profile tile generation performance
  - [ ] Implement parallel tile generation (use all CPU cores)
  - [ ] Skip generating tiles for zoom levels with no data
  - [ ] Use RAM disk for temporary tile storage during generation
  - [ ] Optimize PNG compression settings
  - [ ] Implement incremental tile updates (only changed areas)
  - [ ] Batch upload tiles to S3 (not one-by-one)
- **Acceptance**: Tile generation for 13 forecast hours completes in <20 minutes, utilizes all CPU cores

---

## Phase 5: Automation and Orchestration

**Section** (or sub-project in Asana)

### TICKET-010: Create Master Pipeline Orchestration Script

- **Priority**: P0 | **Effort**: M (4-8 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create `scripts/pipeline.sh`
  - [ ] Calculate model run time (current UTC - 3 hours)
  - [ ] Call download script
  - [ ] Call GDAL processing (via Docker)
  - [ ] Call tile generation (if enabled)
  - [ ] Upload processed files to S3
  - [ ] Generate and upload metadata (latest.json)
  - [ ] Add error handling and rollback logic
  - [ ] Log all steps with timestamps
  - [ ] Send CloudWatch metrics
  - [ ] Clean up temporary files
  - [ ] Add dry-run mode for testing
- **Acceptance**: Pipeline runs end-to-end successfully, completes in <30 minutes, handles errors gracefully

### TICKET-011: Configure Cron Job for Hourly Execution

- **Priority**: P0 | **Effort**: S (<4 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create cron entry for hourly execution
  - [ ] Configure proper environment variables in cron
  - [ ] Set up log rotation for pipeline logs
  - [ ] Test cron job execution
  - [ ] Add monitoring for missed cron executions
  - [ ] Configure email/SNS alerts for failures
  - [ ] Document cron schedule and timezone (UTC)
- **Acceptance**: Cron job runs at :15 past each hour, pipeline executes successfully, logs rotated

### TICKET-012: Create Metadata Generation Script

- **Priority**: P1 | **Effort**: S (<4 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create `scripts/generate_metadata.py`
  - [ ] Calculate model run timestamp
  - [ ] List available forecast hours
  - [ ] Generate tile URL template
  - [ ] Include forecast validity times
  - [ ] Add data age/freshness indicator
  - [ ] Upload to S3 with cache-control headers
  - [ ] Validate JSON schema
- **Acceptance**: JSON file is valid and parseable, contains all required fields, uploaded to S3 with correct headers

---

## Phase 6: Web Application

**Section** (or sub-project in Asana)

### TICKET-013: Create Mapbox Web Application

- **Priority**: P1 | **Effort**: L (1-3 days) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create `web/index.html` with map container
  - [ ] Initialize Mapbox GL JS map
  - [ ] Load latest forecast from `metadata/latest.json`
  - [ ] Add raster layer for temperature tiles
  - [ ] Implement forecast hour selector (F00-F12)
  - [ ] Add animation controls (play/pause forecast timeline)
  - [ ] Display legend with temperature scale
  - [ ] Add location search
  - [ ] Show current mouse cursor temperature value
  - [ ] Implement responsive design for mobile
  - [ ] Add loading states and error handling
  - [ ] Auto-refresh on new forecast availability
- **Acceptance**: Map loads and displays temperature tiles, can switch between forecast hours, works on mobile

### TICKET-014: Implement Forecast Hour Animation

- **Priority**: P2 | **Effort**: M (4-8 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create animation controller class
  - [ ] Implement play/pause controls
  - [ ] Add speed control (1x, 2x, 4x)
  - [ ] Create timeline slider
  - [ ] Show current forecast validity time
  - [ ] Preload all forecast hour tiles
  - [ ] Smooth transitions between forecast hours
  - [ ] Loop animation option
- **Acceptance**: Animation plays smoothly through all forecast hours, can pause at any hour, smooth transitions

### TICKET-015: Deploy Web Application to S3 + CloudFront

- **Priority**: P1 | **Effort**: S (<4 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create S3 bucket for static website hosting
  - [ ] Configure bucket for public read access
  - [ ] Upload web application files
  - [ ] Create CloudFront distribution
  - [ ] Configure custom domain (optional)
  - [ ] Set up SSL certificate with ACM
  - [ ] Configure CloudFront cache behaviors
  - [ ] Test deployment
- **Acceptance**: Web app accessible via CloudFront URL, HTTPS enabled, fast load times globally (<2 seconds)

---

## Phase 7: Monitoring and Observability

**Section** (or sub-project in Asana)

### TICKET-016: Set Up CloudWatch Monitoring

- **Priority**: P1 | **Effort**: M (4-8 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create custom CloudWatch metrics:
    - [ ] `DataAge`: Minutes since model run
    - [ ] `ProcessingTime`: Total pipeline duration
    - [ ] `FilesProcessed`: Count of successful files
    - [ ] `Errors`: Pipeline failure count
    - [ ] `S3StorageSize`: Total storage used
  - [ ] Configure CloudWatch Logs agent on EC2
  - [ ] Create log groups for pipeline components
  - [ ] Set up log retention (30 days)
  - [ ] Create metric filters for errors
  - [ ] Send metrics from Python scripts using boto3
- **Acceptance**: Metrics appear in CloudWatch console, logs are searchable, can create custom dashboards

### TICKET-017: Create CloudWatch Alarms

- **Priority**: P1 | **Effort**: S (<4 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create SNS topic for alerts
  - [ ] Subscribe email to SNS topic
  - [ ] Create alarms:
    - [ ] **Data Stale**: DataAge > 120 minutes
    - [ ] **Pipeline Failed**: Errors > 0 in last hour
    - [ ] **Processing Slow**: ProcessingTime > 35 minutes
    - [ ] **Disk Full**: EC2 disk usage > 80%
    - [ ] **S3 Storage High**: Storage > 500GB (cost control)
  - [ ] Test alarm notifications
  - [ ] Document alarm response procedures
- **Acceptance**: Alarms trigger on threshold breach, email notifications received, alarms visible in console

### TICKET-018: Create CloudWatch Dashboard

- **Priority**: P2 | **Effort**: S (<4 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create CloudWatch dashboard
  - [ ] Add widgets for key metrics:
    - [ ] Data age graph (last 24 hours)
    - [ ] Processing time trend
    - [ ] Files processed per run
    - [ ] Error count
    - [ ] S3 storage growth
    - [ ] EC2 CPU and memory utilization
  - [ ] Add log insights queries
  - [ ] Share dashboard URL
  - [ ] Export dashboard JSON for version control
- **Acceptance**: Dashboard shows real-time metrics, all widgets display data correctly, updates automatically

---

## Phase 8: Testing and Validation

**Section** (or sub-project in Asana)

### TICKET-019: Create Integration Test Suite

- **Priority**: P1 | **Effort**: M (4-8 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Create `tests/` directory
  - [ ] Write test for HRRR download:
    - [ ] Mock NOAA S3 responses
    - [ ] Verify file download
    - [ ] Verify S3 upload
  - [ ] Write test for GDAL processing:
    - [ ] Use sample GRIB2 file
    - [ ] Verify COG creation
    - [ ] Validate COG properties
  - [ ] Write test for tile generation
  - [ ] Write test for metadata generation
  - [ ] Write test for full pipeline
  - [ ] Set up pytest framework
  - [ ] Add test data fixtures
  - [ ] Create CI/CD pipeline (optional)
- **Acceptance**: All tests pass: `pytest tests/`, test coverage > 70%, tests run in <5 minutes

### TICKET-020: Perform Load Testing on Tile Serving

- **Priority**: P2 | **Effort**: M (4-8 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Set up load testing tool (Apache Bench or Locust)
  - [ ] Create test scenarios:
    - [ ] 100 concurrent users panning map
    - [ ] 1000 requests per second to tile endpoint
    - [ ] Sustained load for 10 minutes
  - [ ] Test with and without CloudFront caching
  - [ ] Measure response times (p50, p95, p99)
  - [ ] Identify bottlenecks
  - [ ] Optimize as needed
  - [ ] Document performance characteristics
- **Acceptance**: Tile endpoint handles 1000 req/s, p95 response time < 500ms, CloudFront cache hit rate > 90%

---

## Phase 9: Documentation and Operations

**Section** (or sub-project in Asana)

### TICKET-021: Write Operational Runbook

- **Priority**: P1 | **Effort**: S (<4 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Document common issues and solutions
  - [ ] Create troubleshooting flowcharts
  - [ ] Document alert response procedures
  - [ ] Create deployment checklist
  - [ ] Document rollback procedures
  - [ ] Add contact information for on-call
  - [ ] Create disaster recovery plan
- **Acceptance**: Runbook covers all common operational tasks, troubleshooting steps are clear and actionable

### TICKET-022: Create Cost Optimization Review

- **Priority**: P2 | **Effort**: S (<4 hours) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Enable AWS Cost Explorer
  - [ ] Tag all resources with project name
  - [ ] Review actual costs after 1 week of operation
  - [ ] Identify highest cost components
  - [ ] Research optimization opportunities:
    - [ ] Use S3 Intelligent-Tiering
    - [ ] Evaluate spot instance savings
    - [ ] Review S3 lifecycle policies effectiveness
    - [ ] Evaluate CloudFront cost vs benefit
  - [ ] Document cost optimization recommendations
  - [ ] Implement approved optimizations
- **Acceptance**: Monthly cost report generated, cost breakdown by service, at least 3 optimization recommendations

---

## Phase 10: Future Enhancements

**Section** (or sub-project in Asana)

### TICKET-023: Add Wind Speed and Precipitation Variables

- **Priority**: P3 | **Effort**: L (1-3 days) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Identify GRIB2 bands for wind speed and precipitation
  - [ ] Update download script to get additional variables
  - [ ] Create color ramps for each variable
  - [ ] Process additional bands in parallel
  - [ ] Update web app to show variable selector
  - [ ] Update S3 bucket organization for multiple variables
  - [ ] Update metadata schema
- **Acceptance**: Can display wind speed and precipitation on map, can toggle between variables, processing time increases by <50%

### TICKET-024: Implement Historical Weather Archive

- **Priority**: P3 | **Effort**: XL (>3 days) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Extend S3 lifecycle policies for archival
  - [ ] Create Glacier storage for long-term retention
  - [ ] Build API to query historical data
  - [ ] Add date picker to web app
  - [ ] Implement historical data playback
  - [ ] Create statistics and analysis tools
- **Acceptance**: Historical data archived, can query via API, date picker works in web app

### TICKET-025: Deploy TiTiler for Dynamic Tile Generation

- **Priority**: P3 | **Effort**: L (1-3 days) | **Status**: 🔴 Not Started
- **Sub-tasks**:
  - [ ] Deploy TiTiler on ECS Fargate
  - [ ] Configure Application Load Balancer
  - [ ] Set up auto-scaling
  - [ ] Update web app to use TiTiler endpoints
  - [ ] Configure caching in CloudFront
  - [ ] Benchmark performance vs pre-generated tiles
  - [ ] Migrate if performance acceptable
- **Acceptance**: TiTiler deployed, web app uses TiTiler endpoints, performance benchmarks completed

---

## Quick Summary for Asana

**Parent Task**: Weather Data Pipeline - Automated Infrastructure

- **Total Sub-tasks**: 25 tickets organized into 10 phases
- **Completed**: 3/25 tickets (12%) ✅
- **Priority Breakdown**:
  - P0 (Critical): 7 tickets (3 complete, 4 remaining)
  - P1 (High): 10 tickets
  - P2 (Medium): 5 tickets
  - P3 (Low): 3 tickets
- **Estimated Timeline**: ~2.5-3 weeks for core implementation
- **Current Status**:
  - ✅ **Phase 1 Complete**: All infrastructure ready (S3, EC2, Docker)
  - 🚀 **Phase 2 Next**: Ready to start TICKET-004 (HRRR Download Script)

**Completed Tickets**:
- ✅ TICKET-001: AWS S3 Infrastructure (2026-01-10)
- ✅ TICKET-002: EC2 Instance Provisioning (2026-01-10)
- ✅ TICKET-003: Docker Container (2026-01-10)

**Next Up**:
- 📝 TICKET-004: Create HRRR Download Script with Herbie (P0, M effort)

**Dependencies**:

- ✅ Phase 1 complete - Ready for Phase 2-3
- Phase 2-3 must be completed before Phase 4-5
- Phase 5 must be completed before Phase 6
- Phase 7 can run parallel with Phase 6
- Phase 8-9 can run after Phase 6 is complete
- Phase 10 is future enhancements
