# Weather Data Pipeline - Implementation Tickets

This document contains a prioritized list of implementation tickets for building the automated weather data pipeline infrastructure.

## 🎯 Revision: Herbie Integration (2026-01-10)

**Major Update**: The implementation plan has been revised to integrate the [Herbie](https://herbie.readthedocs.io/) Python package for weather data access. This provides significant benefits:

### What Changed
- **TICKET-003**: Updated Docker container to include Herbie, cfgrib, and eccodes dependencies
- **TICKET-004**: Replaced manual HRRR download implementation with Herbie-based approach (effort reduced from L to M)
- **TICKET-005**: Simplified from band identification tool to variable configuration system (effort reduced from S to XS)
- **TICKET-006**: Updated to use xarray/rioxarray workflow instead of pure GDAL (effort reduced from L to M)

### Why Herbie
- **Faster Development**: ~3-4 days saved by leveraging battle-tested library
- **More Robust**: Automatic fallback across multiple data sources (AWS, Google Cloud, NOMADS, Azure)
- **Better DX**: Simple API replaces complex .idx parsing and byte-range logic
- **Future-Proof**: Easy to add 15+ other models (GFS, RAP, GEFS, ECMWF) with minimal code changes
- **Community Support**: Actively maintained by NOAA/weather community

### Impact on Timeline
- **Original**: ~3-4 weeks for core implementation
- **With Herbie**: ~2.5-3 weeks for core implementation
- **Savings**: 3-4 development days

## Legend

- **Priority**: P0 (Critical), P1 (High), P2 (Medium), P3 (Low)
- **Effort**: XS (Extra Small, <2 hours), S (Small, <4 hours), M (Medium, 4-8 hours), L (Large, 1-3 days), XL (Extra Large, >3 days)
- **Status**: 🔴 Not Started | 🟡 In Progress | 🟢 Complete

---

## Phase 1: Infrastructure Setup

### TICKET-001: Set Up AWS Infrastructure with Terraform

**Priority**: P0 | **Effort**: M | **Status**: 🟡 (Partial - bucket exists)

**Description**:
Update existing Terraform configuration to support the full weather pipeline infrastructure including S3 buckets with proper organization, IAM roles, and lifecycle policies.

**Tasks**:

- [ ] Update `main.tf` to create organized S3 bucket structure (raw-grib2/, processed-cog/, tiles/, metadata/)
- [ ] Create S3 lifecycle policies for automated data retention
  - [ ] raw-grib2: Delete after 7 days
  - [ ] processed-cog: Transition to Standard-IA after 2 days, delete after 30 days
  - [ ] tiles: Delete after 3 days (if using pre-generated tiles)
- [ ] Create IAM role for EC2 instance with S3 read/write permissions
- [ ] Create IAM policy for CloudWatch metrics and logs
- [ ] Add CloudFront distribution (optional for CDN)
- [ ] Configure CORS for S3 bucket to allow web access
- [ ] Add versioning for processed-cog bucket (for rollback capability)

**Acceptance Criteria**:

- [ ] `terraform plan` shows correct resource changes
- [ ] `terraform apply` successfully creates all resources
- [ ] S3 bucket structure matches specification
- [ ] Lifecycle policies are active and verified
- [ ] IAM role can be assumed by EC2 instance
- [ ] Manual file upload/download works with correct permissions

**Files to Create/Modify**:

- `terraform/main.tf`
- `terraform/lifecycle-policies.tf` (new)
- `terraform/iam.tf` (new)
- `terraform/cloudfront.tf` (new, optional)
- `terraform/variables.tf`
- `terraform/outputs.tf`

---

### TICKET-002: Provision EC2 Instance for Data Processing

**Priority**: P0 | **Effort**: S

**Description**:
Launch and configure an EC2 instance to run the automated pipeline. Use spot instance for cost savings.

**Tasks**:

- [ ] Launch EC2 t3.small spot instance in us-east-1
- [ ] Configure security group (allow SSH from your IP only)
- [ ] Attach IAM role from TICKET-001
- [ ] Install system dependencies:
  - [ ] Docker
  - [ ] AWS CLI v2
  - [ ] Python 3.10+
  - [ ] pip
  - [ ] git
- [ ] Configure AWS CLI with credentials/role
- [ ] Set up CloudWatch Logs agent
- [ ] Create working directory: `/home/ubuntu/weather-pipeline/`
- [ ] Configure spot instance interruption handling

**Acceptance Criteria**:

- [ ] Can SSH into instance
- [ ] Docker runs without sudo: `docker run hello-world`
- [ ] AWS CLI configured: `aws s3 ls s3://your-bucket/`
- [ ] Python 3.10+ installed: `python3 --version`
- [ ] CloudWatch agent running and sending logs
- [ ] 50GB EBS volume attached for temporary processing

**Commands**:

```bash
# Launch spot instance
aws ec2 request-spot-instances \
  --spot-price "0.02" \
  --instance-count 1 \
  --type "one-time" \
  --launch-specification file://spot-instance-spec.json
```

---

### TICKET-003: Create Docker Container for Weather Data Processing

**Priority**: P0 | **Effort**: M

**Description**:
Build a Docker container with GDAL, Herbie, and all necessary dependencies for downloading and processing weather forecast data.

**Tasks**:

- [ ] Create `docker/Dockerfile` based on `osgeo/gdal:ubuntu-small-3.8.0`
- [ ] Install Python dependencies (herbie-data, rioxarray, xarray, boto3, pyyaml)
- [ ] Create `docker/requirements.txt`
- [ ] Install cfgrib and eccodes for GRIB2 support (required by Herbie)
- [ ] Add processing scripts to container
- [ ] Test download and processing workflow locally
- [ ] Build and tag image: `weather-processor:latest`
- [ ] Test container with sample HRRR download
- [ ] Document resource requirements (memory, CPU)
- [ ] Optimize image size (<800MB with all dependencies)

**Acceptance Criteria**:

- [ ] Docker image builds successfully
- [ ] Image size < 800MB
- [ ] Can download data with Herbie inside container
- [ ] Can process NetCDF to COG inside container
- [ ] Can read from and write to S3 from container
- [ ] GDAL version 3.6+ installed
- [ ] Herbie, cfgrib, and all dependencies working
- [ ] No permission issues when running container

**Files to Create**:

```
docker/
├── Dockerfile
├── requirements.txt
└── .dockerignore
```

**requirements.txt**:

```txt
# Weather data access
herbie-data>=2024.0.0

# Geospatial processing
rioxarray>=0.15.0
xarray>=2023.0.0
cfgrib>=0.9.10
eccodes>=1.6.0

# AWS integration
boto3>=1.28.0

# Configuration
pyyaml>=6.0

# Utilities
pandas>=2.0.0
numpy>=1.24.0
requests>=2.31.0
```

**Dockerfile**:

```dockerfile
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.8.0

# Install system dependencies for eccodes (required by cfgrib/Herbie)
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    libeccodes-dev \
    libeccodes-tools \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python requirements
COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# Set environment variables for eccodes
ENV ECCODES_DIR=/usr
ENV ECCODES_DEFINITION_PATH=/usr/share/eccodes/definitions

# Create working directory
WORKDIR /app

# Copy scripts (will be mounted or copied during build)
COPY scripts/ /app/

# Set Python to unbuffered mode for better logging
ENV PYTHONUNBUFFERED=1

# Default command
CMD ["python3", "--version"]
```

**.dockerignore**:

```
**/__pycache__
**/*.pyc
**/*.pyo
**/*.pyd
**/.Python
**/env
**/venv
**/.env
**/.venv
**/.git
**/.gitignore
**/.dockerignore
**/Dockerfile
**/docker-compose.yml
**/.pytest_cache
**/.coverage
**/htmlcov
**/*.log
**/test-data/
```

**Build and Test Commands**:

```bash
# Build image
cd docker/
docker build -t weather-processor:latest .

# Test Herbie installation
docker run --rm weather-processor:latest python3 -c "from herbie import Herbie; print('Herbie OK')"

# Test with actual download (requires internet)
docker run --rm \
  -v /tmp:/tmp \
  -e AWS_REGION=us-east-1 \
  weather-processor:latest \
  python3 -c "from herbie import Herbie; H = Herbie('2026-01-09 12:00', model='hrrr', fxx=0); print(H)"
```

---

## Phase 2: Data Ingestion Scripts

### TICKET-004: Create HRRR Download Script with Herbie

**Priority**: P0 | **Effort**: M (reduced from L)

**Description**:
Build Python script using Herbie package to download HRRR forecast data. Herbie simplifies access to weather model data with automatic byte-range downloads, multi-source fallback, and native xarray integration.

**Tasks**:

- [ ] Create `scripts/download_hrrr.py` using Herbie
- [ ] Install herbie-data package in Docker container
- [ ] Download forecast hours F00-F12 for specified variables
- [ ] Use Herbie's smart download for specific variables (TMP:2 m, UGRD:10 m, VGRD:10 m)
- [ ] Save downloaded data as NetCDF or retain GRIB2 format
- [ ] Upload processed data to S3 with timestamped paths
- [ ] Add logging with timestamps
- [ ] Handle missing or delayed NOAA data gracefully (Herbie auto-fallback to other sources)
- [ ] Add command-line arguments (--date, --cycle, --forecast-hours, --variables)
- [ ] Create unit tests

**Acceptance Criteria**:

- [ ] Can download single forecast hour successfully
- [ ] Can download all 13 forecast hours (F00-F12)
- [ ] Downloads only requested variables (reduces data transfer by >80%)
- [ ] Data loaded into xarray Dataset for immediate processing
- [ ] Script handles network errors gracefully with Herbie's retry logic
- [ ] Logging shows progress and timing
- [ ] Script completes in <5 minutes for 13 forecast hours
- [ ] Automatic fallback to alternate sources if primary source unavailable

**File Structure**:

```python
# scripts/download_hrrr.py

import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from herbie import Herbie, FastHerbie
import xarray as xr

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def download_forecast(date, fxx_range, variables, output_dir):
    """
    Download HRRR forecast data using Herbie

    Args:
        date: Model run date (datetime or str)
        fxx_range: Range of forecast hours (e.g., range(0, 13))
        variables: List of GRIB2 search strings (e.g., ['TMP:2 m', 'UGRD:10 m'])
        output_dir: Directory to save data
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    downloaded_files = []

    for fxx in fxx_range:
        logger.info(f"Downloading forecast hour F{fxx:02d}...")

        try:
            # Create Herbie object for this forecast hour
            H = Herbie(
                date,
                model='hrrr',
                product='sfc',  # surface fields
                fxx=fxx
            )

            # Download multiple variables efficiently
            for var in variables:
                logger.info(f"  Downloading {var}...")

                # Download and load into xarray
                ds = H.xarray(var, remove_grib=False)

                # Save to NetCDF for processing
                var_name = var.split(':')[0].lower()
                output_file = output_path / f"hrrr_{H.date:%Y%m%d_%H}z_f{fxx:02d}_{var_name}.nc"
                ds.to_netcdf(output_file)

                downloaded_files.append(output_file)
                logger.info(f"  Saved to {output_file}")

        except Exception as e:
            logger.error(f"Error downloading F{fxx:02d}: {e}")
            continue

    return downloaded_files

def download_batch_forecast(dates, fxx_range, variables, output_dir):
    """
    Download multiple forecast runs efficiently using FastHerbie

    Useful for bulk downloads or backfilling data
    """
    logger.info(f"Batch downloading {len(dates)} model runs...")

    # FastHerbie enables parallel downloads
    FH = FastHerbie(
        dates,
        model='hrrr',
        fxx=list(fxx_range)
    )

    # Download all at once
    for var in variables:
        logger.info(f"Downloading {var} for all forecast hours...")
        FH.xarray(var, max_threads=4)

def upload_to_s3(local_files, bucket, s3_prefix):
    """Upload files to S3 with timestamp organization"""
    import boto3

    s3 = boto3.client('s3')

    for file_path in local_files:
        s3_key = f"{s3_prefix}/{file_path.name}"
        logger.info(f"Uploading {file_path.name} to s3://{bucket}/{s3_key}")
        s3.upload_file(str(file_path), bucket, s3_key)

def main():
    parser = argparse.ArgumentParser(description='Download HRRR data using Herbie')
    parser.add_argument('--date', help='Model run date (YYYY-MM-DD HH:MM)',
                       default=(datetime.utcnow() - timedelta(hours=3)).strftime('%Y-%m-%d %H:00'))
    parser.add_argument('--forecast-hours', default='0-12', help='Forecast hour range (e.g., 0-12)')
    parser.add_argument('--variables', nargs='+',
                       default=['TMP:2 m'],
                       help='Variables to download (e.g., "TMP:2 m" "UGRD:10 m")')
    parser.add_argument('--output-dir', default='/tmp/hrrr-data', help='Output directory')
    parser.add_argument('--s3-bucket', help='S3 bucket for upload (optional)')
    parser.add_argument('--s3-prefix', default='raw-grib2', help='S3 prefix')

    args = parser.parse_args()

    # Parse forecast hour range
    start, end = map(int, args.forecast_hours.split('-'))
    fxx_range = range(start, end + 1)

    logger.info(f"Starting download for {args.date}")
    logger.info(f"Forecast hours: F{start:02d}-F{end:02d}")
    logger.info(f"Variables: {args.variables}")

    # Download data
    downloaded_files = download_forecast(
        args.date,
        fxx_range,
        args.variables,
        args.output_dir
    )

    logger.info(f"Downloaded {len(downloaded_files)} files")

    # Upload to S3 if specified
    if args.s3_bucket:
        upload_to_s3(downloaded_files, args.s3_bucket, args.s3_prefix)

    logger.info("Download complete!")

if __name__ == '__main__':
    main()
```

**Herbie Advantages**:
- Automatic .idx parsing and byte-range downloads
- Built-in retry logic and error handling
- Multi-source fallback (AWS → Google Cloud → NOMADS → Azure)
- Direct xarray integration (no intermediate GRIB2 files needed)
- Support for 15+ weather models (easy to add GFS, RAP, etc.)
- FastHerbie for parallel bulk downloads

---

### TICKET-005: Create Variable Configuration System

**Priority**: P1 | **Effort**: XS (reduced from S, simplified scope)

**Description**:
Create configuration file to manage which weather variables to download and process. With Herbie, variables are referenced by GRIB2 search strings rather than band numbers.

**Tasks**:

- [ ] Create `config/variables.yaml` configuration file
- [ ] Define variable mappings with Herbie search strings
- [ ] Include visualization settings (color ramps, units, display names)
- [ ] Add metadata for each variable (description, units, typical range)
- [ ] Create helper script to list available variables from a model
- [ ] Validate configuration on startup

**Acceptance Criteria**:

- [ ] Configuration file is valid YAML
- [ ] All variables have required fields
- [ ] Helper script can query available variables from HRRR
- [ ] Easy to add new variables without code changes

**Configuration Example** (`config/variables.yaml`):

```yaml
variables:
  temperature_2m:
    herbie_search: "TMP:2 m"
    display_name: "Temperature (2m)"
    units: "Kelvin"
    units_display: "°C"
    conversion: "kelvin_to_celsius"
    typical_range: [-40, 50]
    color_ramp: "temperature-jet"
    description: "Temperature at 2 meters above ground"

  wind_speed_10m:
    herbie_search: "UGRD:10 m|VGRD:10 m"  # Download both U and V components
    display_name: "Wind Speed (10m)"
    units: "m/s"
    units_display: "mph"
    conversion: "ms_to_mph"
    typical_range: [0, 100]
    color_ramp: "wind-speed"
    description: "Wind speed at 10 meters above ground"

  precipitation:
    herbie_search: "APCP"
    display_name: "Accumulated Precipitation"
    units: "kg/m^2"
    units_display: "inches"
    conversion: "kgm2_to_inches"
    typical_range: [0, 5]
    color_ramp: "precipitation"
    description: "Total accumulated precipitation"

# Helper script to discover variables
# python scripts/list_variables.py --model hrrr --date "2026-01-09 12:00"
```

**Helper Script** (`scripts/list_variables.py`):

```python
#!/usr/bin/env python3
"""List available variables in a weather model"""

import argparse
from herbie import Herbie

def list_variables(date, model='hrrr', fxx=0):
    """List all available variables in a model run"""
    H = Herbie(date, model=model, fxx=fxx)

    # Get the inventory (list of all variables)
    inventory = H.inventory()

    print(f"\nAvailable variables in {model.upper()} for {date}, F{fxx:02d}:\n")
    print(f"{'Variable':<40} {'Level':<20} {'Description':<50}")
    print("-" * 110)

    for idx, row in inventory.iterrows():
        print(f"{row['search_this']:<40} {row['level']:<20} {row['param']:<50}")

    return inventory

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default='2026-01-09 12:00')
    parser.add_argument('--model', default='hrrr')
    parser.add_argument('--fxx', type=int, default=0)
    args = parser.parse_args()

    list_variables(args.date, args.model, args.fxx)
```

---

## Phase 3: GDAL Processing Pipeline

### TICKET-006: Create Data Processing Script with rioxarray

**Priority**: P0 | **Effort**: M (reduced from L)

**Description**:
Build Python script to process weather data from xarray Datasets (via Herbie) into Cloud Optimized GeoTIFFs. Uses rioxarray for reprojection and GDAL for COG creation.

**Tasks**:

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

**Acceptance Criteria**:

- [ ] Processes single NetCDF file to COG successfully
- [ ] Output COG is <5MB with compression
- [ ] COG is properly georeferenced in EPSG:3857
- [ ] Can process 13 files in <10 minutes
- [ ] Utilizes multiple CPU cores efficiently
- [ ] Output files pass COG validation: `rio cogeo validate output.tif`
- [ ] Includes overviews for zoom levels 1-10

**Processing Script**:

```python
# scripts/process_weather.py

import argparse
import logging
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import xarray as xr
import rioxarray
from osgeo import gdal

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def kelvin_to_celsius(da):
    """Convert temperature from Kelvin to Celsius"""
    return da - 273.15

def process_to_cog(input_nc, output_tif, target_crs='EPSG:3857', variable=None):
    """
    Process NetCDF to Cloud Optimized GeoTIFF

    Args:
        input_nc: Path to input NetCDF file
        output_tif: Path to output COG file
        target_crs: Target coordinate reference system
        variable: Variable name to extract (if None, uses first data variable)
    """
    logger.info(f"Processing {input_nc.name}...")

    try:
        # Load NetCDF with rioxarray
        ds = xr.open_dataset(input_nc)

        # Select variable (temperature, wind, etc.)
        if variable is None:
            variable = list(ds.data_vars)[0]

        da = ds[variable]

        # Apply unit conversions if needed
        if 'temperature' in str(variable).lower() or variable == 't2m':
            logger.info("  Converting Kelvin to Celsius...")
            da = kelvin_to_celsius(da)
            da.attrs['units'] = 'Celsius'

        # Set spatial dimensions if not already set
        if not hasattr(da, 'rio'):
            # Herbie data usually comes with proper georeferencing
            da = da.rio.write_crs("EPSG:4326")  # HRRR native is usually lat/lon

        # Reproject to Web Mercator
        logger.info(f"  Reprojecting to {target_crs}...")
        da_reproj = da.rio.reproject(
            target_crs,
            resampling='bilinear',
            nodata=-9999
        )

        # Write to temporary GeoTIFF
        temp_tif = output_tif.parent / f"{output_tif.stem}_temp.tif"
        da_reproj.rio.to_raster(
            temp_tif,
            driver='GTiff',
            compress='DEFLATE',
            tiled=True,
            blockxsize=256,
            blockysize=256
        )

        # Convert to COG with overviews
        logger.info("  Creating Cloud Optimized GeoTIFF...")
        gdal.Translate(
            str(output_tif),
            str(temp_tif),
            format='COG',
            creationOptions=[
                'COMPRESS=DEFLATE',
                'BLOCKSIZE=256',
                'OVERVIEW_RESAMPLING=BILINEAR',
                'NUM_THREADS=ALL_CPUS',
                'BIGTIFF=IF_SAFER'
            ]
        )

        # Clean up temp file
        temp_tif.unlink()

        logger.info(f"  Created {output_tif.name} ({output_tif.stat().st_size / 1024 / 1024:.2f} MB)")
        return output_tif

    except Exception as e:
        logger.error(f"Error processing {input_nc.name}: {e}")
        raise

def process_batch(input_dir, output_dir, variable=None, max_workers=4):
    """Process multiple NetCDF files in parallel"""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Find all NetCDF files
    nc_files = sorted(input_path.glob('*.nc'))
    logger.info(f"Found {len(nc_files)} files to process")

    # Process in parallel
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for nc_file in nc_files:
            output_file = output_path / f"{nc_file.stem}.tif"
            future = executor.submit(process_to_cog, nc_file, output_file, variable=variable)
            futures.append(future)

        # Wait for completion
        results = [f.result() for f in futures]

    logger.info(f"Processed {len(results)} files successfully")
    return results

def main():
    parser = argparse.ArgumentParser(description='Process weather data to COG format')
    parser.add_argument('--input-dir', required=True, help='Directory with NetCDF files')
    parser.add_argument('--output-dir', required=True, help='Output directory for COGs')
    parser.add_argument('--variable', help='Variable name to extract')
    parser.add_argument('--workers', type=int, default=4, help='Number of parallel workers')
    parser.add_argument('--target-crs', default='EPSG:3857', help='Target CRS')

    args = parser.parse_args()

    process_batch(
        args.input_dir,
        args.output_dir,
        variable=args.variable,
        max_workers=args.workers
    )

if __name__ == '__main__':
    main()
```

**Advantages of xarray/rioxarray Approach**:
- Direct integration with Herbie output (no GRIB2 intermediate files)
- Easier unit conversions and data transformations
- Native support for NetCDF and COG output
- Better error handling and metadata preservation
- Simpler parallel processing with dask if needed

---

### TICKET-007: Add Color Ramp and Visualization Styling

**Priority**: P1 | **Effort**: M

**Description**:
Apply color ramps to temperature data for better visualization in web maps. Convert to 8-bit RGB for smaller file sizes.

**Tasks**:

- [ ] Create color ramp configuration file (JSON)
- [ ] Define temperature ranges and colors (e.g., -40°C to 50°C)
- [ ] Implement `gdaldem color-relief` in processing pipeline
- [ ] Convert to 8-bit RGB with transparency
- [ ] Generate PNG tiles for web serving
- [ ] Create multiple color schemes (temperature, precipitation, wind)
- [ ] Add command-line option to select color scheme
- [ ] Document color ramp customization

**Acceptance Criteria**:

- [ ] Output files have color applied
- [ ] Temperature ranges map to intuitive colors (blue=cold, red=hot)
- [ ] File sizes reduced by converting to 8-bit
- [ ] Transparent background outside data extent
- [ ] Can switch between different color schemes

**Color Ramp Example** (`config/color-ramp-temperature.txt`):

```
# Temperature color ramp (Kelvin to RGB)
250 0 0 255      # -23°C = Blue
260 50 100 255   # -13°C = Light Blue
273 200 255 255  # 0°C = Cyan
283 0 255 0      # 10°C = Green
293 255 255 0    # 20°C = Yellow
303 255 128 0    # 30°C = Orange
313 255 0 0      # 40°C = Red
```

---

## Phase 4: Tile Generation

### TICKET-008: Implement Tile Generation Strategy

**Priority**: P1 | **Effort**: M

**Description**:
Decide on and implement tile generation approach: either pre-generated tiles with gdal2tiles, or dynamic tiles with TiTiler.

**Tasks**:

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

**Acceptance Criteria**:

- [ ] Tiles render correctly in Mapbox
- [ ] Zoom levels 1-10 are available
- [ ] Tiles load in <500ms
- [ ] Transparent areas show basemap underneath
- [ ] Tile generation completes within processing time budget

**Decision Matrix**:
| Criteria | Pre-generated Tiles | Dynamic TiTiler |
|----------|-------------------|-----------------|
| Storage | High (1-2GB per forecast) | Low (3MB COG) |
| Speed | Fast (pre-rendered) | Fast (cached) |
| Flexibility | Low (must regenerate) | High (runtime styling) |
| Cost | Medium | Medium |

---

### TICKET-009: Optimize Tile Generation Performance

**Priority**: P2 | **Effort**: M

**Description**:
If using pre-generated tiles, optimize the tile generation process to complete within the hourly processing window.

**Tasks**:

- [ ] Profile tile generation performance
- [ ] Implement parallel tile generation (use all CPU cores)
- [ ] Skip generating tiles for zoom levels with no data
- [ ] Use RAM disk for temporary tile storage during generation
- [ ] Optimize PNG compression settings
- [ ] Implement incremental tile updates (only changed areas)
- [ ] Batch upload tiles to S3 (not one-by-one)

**Acceptance Criteria**:

- [ ] Tile generation for 13 forecast hours completes in <20 minutes
- [ ] Utilizes all available CPU cores
- [ ] S3 upload uses batch operations
- [ ] Total processing time (GDAL + tiles) < 30 minutes

---

## Phase 5: Automation and Orchestration

### TICKET-010: Create Master Pipeline Orchestration Script

**Priority**: P0 | **Effort**: M

**Description**:
Build main bash script that orchestrates the entire pipeline: download, process, tile generation, upload, and metadata update.

**Tasks**:

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

**Acceptance Criteria**:

- [ ] Pipeline runs end-to-end successfully
- [ ] Completes in <30 minutes
- [ ] Handles errors gracefully (retries, alerts)
- [ ] Logs are detailed and timestamped
- [ ] Cleans up temporary files
- [ ] Sends success/failure metrics to CloudWatch
- [ ] Can run in dry-run mode without side effects

**Script Structure**:

```bash
#!/bin/bash
# scripts/pipeline.sh

set -e  # Exit on error
set -o pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/var/log/weather-pipeline.log"
S3_BUCKET="${S3_BUCKET:-your-weather-bucket}"

# Functions
log() { echo "[$(date -u +"%Y-%m-%d %H:%M:%S")] $*" | tee -a "$LOG_FILE"; }
error() { log "ERROR: $*"; exit 1; }
cleanup() { log "Cleaning up temporary files..."; rm -rf /tmp/hrrr-*; }

trap cleanup EXIT

# Main pipeline
main() {
    log "Starting weather pipeline..."

    # 1. Download
    log "Step 1: Downloading HRRR data..."
    python3 "$SCRIPT_DIR/download_hrrr.py" || error "Download failed"

    # 2. Process
    log "Step 2: Processing with GDAL..."
    docker run --rm \
        -v /tmp:/tmp \
        -v ~/.aws:/root/.aws \
        weather-processor:latest || error "Processing failed"

    # 3. Upload
    log "Step 3: Uploading to S3..."
    python3 "$SCRIPT_DIR/upload_to_s3.py" || error "Upload failed"

    # 4. Metadata
    log "Step 4: Updating metadata..."
    python3 "$SCRIPT_DIR/generate_metadata.py" || error "Metadata update failed"

    log "Pipeline complete!"
}

main "$@"
```

---

### TICKET-011: Configure Cron Job for Hourly Execution

**Priority**: P0 | **Effort**: S

**Description**:
Set up cron job on EC2 instance to run pipeline hourly at HH:15 (15 minutes past each hour).

**Tasks**:

- [ ] Create cron entry for hourly execution
- [ ] Configure proper environment variables in cron
- [ ] Set up log rotation for pipeline logs
- [ ] Test cron job execution
- [ ] Add monitoring for missed cron executions
- [ ] Configure email/SNS alerts for failures
- [ ] Document cron schedule and timezone (UTC)

**Acceptance Criteria**:

- [ ] Cron job runs at :15 past each hour
- [ ] Pipeline executes successfully from cron
- [ ] Logs are written to `/var/log/weather-pipeline.log`
- [ ] Log rotation prevents disk fill-up
- [ ] Failures trigger alerts

**Crontab Configuration**:

```bash
# Edit crontab
crontab -e

# Add this line (runs at :15 past every hour)
15 * * * * /bin/bash /home/ubuntu/weather-pipeline/scripts/pipeline.sh >> /var/log/weather-pipeline.log 2>&1

# Set environment variables
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
AWS_REGION=us-east-1
S3_BUCKET=your-weather-bucket
```

**Log Rotation** (`/etc/logrotate.d/weather-pipeline`):

```
/var/log/weather-pipeline.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 ubuntu ubuntu
}
```

---

### TICKET-012: Create Metadata Generation Script

**Priority**: P1 | **Effort**: S

**Description**:
Generate `latest.json` metadata file that web app uses to discover the most recent forecast and tile URLs.

**Tasks**:

- [ ] Create `scripts/generate_metadata.py`
- [ ] Calculate model run timestamp
- [ ] List available forecast hours
- [ ] Generate tile URL template
- [ ] Include forecast validity times
- [ ] Add data age/freshness indicator
- [ ] Upload to S3 with cache-control headers
- [ ] Validate JSON schema

**Acceptance Criteria**:

- [ ] JSON file is valid and parseable
- [ ] Contains all required fields
- [ ] Uploaded to S3 with correct cache headers
- [ ] Web app can load and parse file

**Metadata Schema** (`metadata/latest.json`):

```json
{
  "modelRun": "2026-01-09T14Z",
  "generatedAt": "2026-01-09T15:35:00Z",
  "dataSource": "HRRR",
  "variable": "temperature_2m",
  "forecastHours": [0, 1, 2, 3, 6, 9, 12],
  "tileUrlTemplate": "https://d123456789.cloudfront.net/tiles/temperature/{modelRun}/f{fhour:02d}/{z}/{x}/{y}.png",
  "cogUrlTemplate": "https://your-bucket.s3.amazonaws.com/processed-cog/temperature/{modelRun}/f{fhour:02d}.tif",
  "projection": "EPSG:3857",
  "bounds": {
    "west": -134.0,
    "south": 20.0,
    "east": -60.0,
    "north": 52.0
  },
  "units": "Kelvin",
  "colorRamp": "temperature-jet"
}
```

---

## Phase 6: Web Application

### TICKET-013: Create Mapbox Web Application

**Priority**: P1 | **Effort**: L

**Description**:
Build web application with Mapbox GL JS to display weather tiles on an interactive map.

**Tasks**:

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

**Acceptance Criteria**:

- [ ] Map loads and displays temperature tiles
- [ ] Can switch between forecast hours
- [ ] Animation plays through forecast hours
- [ ] Legend shows temperature colors
- [ ] Works on desktop and mobile browsers
- [ ] Handles missing data gracefully
- [ ] Auto-detects new forecasts every 5 minutes

**Files to Create**:

```
web/
├── index.html
├── weather-map.js
├── styles.css
└── config.js
```

---

### TICKET-014: Implement Forecast Hour Animation

**Priority**: P2 | **Effort**: M

**Description**:
Add animation feature to cycle through forecast hours automatically, showing temperature evolution over time.

**Tasks**:

- [ ] Create animation controller class
- [ ] Implement play/pause controls
- [ ] Add speed control (1x, 2x, 4x)
- [ ] Create timeline slider
- [ ] Show current forecast validity time
- [ ] Preload all forecast hour tiles
- [ ] Smooth transitions between forecast hours
- [ ] Loop animation option

**Acceptance Criteria**:

- [ ] Animation plays smoothly through all forecast hours
- [ ] Can pause at any forecast hour
- [ ] Timeline slider shows current position
- [ ] Forecast time updates in UI
- [ ] Smooth fade transitions between hours

**UI Controls**:

```
[◄◄] [▶/⏸] [►►]  [====●====] F06 - Valid: 2026-01-09 20:00 UTC
```

---

### TICKET-015: Deploy Web Application to S3 + CloudFront

**Priority**: P1 | **Effort**: S

**Description**:
Host the web application on S3 with CloudFront for fast global access.

**Tasks**:

- [ ] Create S3 bucket for static website hosting
- [ ] Configure bucket for public read access
- [ ] Upload web application files
- [ ] Create CloudFront distribution
- [ ] Configure custom domain (optional)
- [ ] Set up SSL certificate with ACM
- [ ] Configure CloudFront cache behaviors
- [ ] Test deployment

**Acceptance Criteria**:

- [ ] Web app accessible via CloudFront URL
- [ ] HTTPS enabled
- [ ] Fast load times globally (<2 seconds)
- [ ] Cache headers configured correctly

---

## Phase 7: Monitoring and Observability

### TICKET-016: Set Up CloudWatch Monitoring

**Priority**: P1 | **Effort**: M

**Description**:
Implement comprehensive monitoring with CloudWatch metrics, logs, and alarms.

**Tasks**:

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

**Acceptance Criteria**:

- [ ] Metrics appear in CloudWatch console
- [ ] Logs are searchable in CloudWatch Logs
- [ ] Can create custom dashboards from metrics
- [ ] Log retention policies active

**Metric Publishing Example**:

```python
import boto3
from datetime import datetime

cloudwatch = boto3.client('cloudwatch')

def send_metric(metric_name, value, unit='None'):
    cloudwatch.put_metric_data(
        Namespace='WeatherPipeline',
        MetricData=[{
            'MetricName': metric_name,
            'Value': value,
            'Unit': unit,
            'Timestamp': datetime.utcnow()
        }]
    )
```

---

### TICKET-017: Create CloudWatch Alarms

**Priority**: P1 | **Effort**: S

**Description**:
Set up alarms to notify when pipeline fails or data becomes stale.

**Tasks**:

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

**Acceptance Criteria**:

- [ ] Alarms trigger on threshold breach
- [ ] Email notifications received
- [ ] Alarms visible in CloudWatch console
- [ ] Can acknowledge and resolve alarms

**Alarm Configuration** (Terraform):

```hcl
resource "aws_cloudwatch_metric_alarm" "data_stale" {
  alarm_name          = "weather-data-stale"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "DataAge"
  namespace           = "WeatherPipeline"
  period              = 300
  statistic           = "Maximum"
  threshold           = 120
  alarm_description   = "Weather data is more than 2 hours old"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
```

---

### TICKET-018: Create CloudWatch Dashboard

**Priority**: P2 | **Effort**: S

**Description**:
Build operational dashboard showing pipeline health and performance metrics.

**Tasks**:

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

**Acceptance Criteria**:

- [ ] Dashboard shows real-time metrics
- [ ] All widgets display data correctly
- [ ] Can access dashboard via URL
- [ ] Dashboard updates automatically

---

## Phase 8: Testing and Validation

### TICKET-019: Create Integration Test Suite

**Priority**: P1 | **Effort**: M

**Description**:
Build automated tests to validate end-to-end pipeline functionality.

**Tasks**:

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

**Acceptance Criteria**:

- [ ] All tests pass: `pytest tests/`
- [ ] Test coverage > 70%
- [ ] Tests run in <5 minutes
- [ ] Tests can run in isolated environment

**Test Structure**:

```
tests/
├── __init__.py
├── test_download.py
├── test_processing.py
├── test_tiles.py
├── test_metadata.py
├── test_integration.py
├── fixtures/
│   └── sample_hrrr.grib2
└── conftest.py
```

---

### TICKET-020: Perform Load Testing on Tile Serving

**Priority**: P2 | **Effort**: M

**Description**:
Test tile serving performance under realistic traffic loads.

**Tasks**:

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

**Acceptance Criteria**:

- [ ] Tile endpoint handles 1000 req/s
- [ ] p95 response time < 500ms
- [ ] CloudFront cache hit rate > 90%
- [ ] No 5xx errors under load

---

## Phase 9: Documentation and Operations

### TICKET-021: Write Operational Runbook

**Priority**: P1 | **Effort**: S

**Description**:
Create operational documentation for common tasks and troubleshooting.

**Tasks**:

- [ ] Document common issues and solutions
- [ ] Create troubleshooting flowcharts
- [ ] Document alert response procedures
- [ ] Create deployment checklist
- [ ] Document rollback procedures
- [ ] Add contact information for on-call
- [ ] Create disaster recovery plan

**Acceptance Criteria**:

- [ ] Runbook covers all common operational tasks
- [ ] Troubleshooting steps are clear and actionable
- [ ] New team members can follow runbook successfully

**Sections**:

```markdown
# Operational Runbook

## Table of Contents

1. Architecture Overview
2. Common Issues and Solutions
3. Alert Response Procedures
4. Deployment Procedures
5. Rollback Procedures
6. Disaster Recovery
7. Contact Information

## Common Issues

### Issue: Pipeline Not Running

**Symptoms**: No new data in S3, DataAge metric increasing
**Diagnosis**:

1. Check cron job: `crontab -l`
2. Check recent logs: `tail -100 /var/log/weather-pipeline.log`
3. Check EC2 instance status

**Resolution**:

1. If cron not running: `sudo service cron restart`
2. If disk full: Clean up /tmp directory
3. If script error: Check logs and fix code
   ...
```

---

### TICKET-022: Create Cost Optimization Review

**Priority**: P2 | **Effort**: S

**Description**:
Analyze actual costs and identify optimization opportunities.

**Tasks**:

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

**Acceptance Criteria**:

- [ ] Monthly cost report generated
- [ ] Cost breakdown by service
- [ ] At least 3 optimization recommendations
- [ ] Actual costs within budget ($25/month target)

---

## Phase 10: Future Enhancements

### TICKET-023: Add Wind Speed and Precipitation Variables

**Priority**: P3 | **Effort**: L

**Description**:
Expand pipeline to process additional weather variables beyond temperature.

**Tasks**:

- [ ] Identify GRIB2 bands for wind speed and precipitation
- [ ] Update download script to get additional variables
- [ ] Create color ramps for each variable
- [ ] Process additional bands in parallel
- [ ] Update web app to show variable selector
- [ ] Update S3 bucket organization for multiple variables
- [ ] Update metadata schema

**Acceptance Criteria**:

- [ ] Can display wind speed on map
- [ ] Can display precipitation on map
- [ ] Can toggle between variables in web app
- [ ] Processing time increases by <50%

---

### TICKET-024: Implement Historical Weather Archive

**Priority**: P3 | **Effort**: XL

**Description**:
Archive processed weather data for historical analysis and playback.

**Tasks**:

- [ ] Extend S3 lifecycle policies for archival
- [ ] Create Glacier storage for long-term retention
- [ ] Build API to query historical data
- [ ] Add date picker to web app
- [ ] Implement historical data playback
- [ ] Create statistics and analysis tools

---

### TICKET-025: Deploy TiTiler for Dynamic Tile Generation

**Priority**: P3 | **Effort**: L

**Description**:
Replace pre-generated tiles with TiTiler for dynamic, on-demand tile generation with runtime styling.

**Tasks**:

- [ ] Deploy TiTiler on ECS Fargate
- [ ] Configure Application Load Balancer
- [ ] Set up auto-scaling
- [ ] Update web app to use TiTiler endpoints
- [ ] Configure caching in CloudFront
- [ ] Benchmark performance vs pre-generated tiles
- [ ] Migrate if performance acceptable

---

## Summary

### Quick Stats

- **Total Tickets**: 25
- **P0 (Critical)**: 7 tickets
- **P1 (High)**: 10 tickets
- **P2 (Medium)**: 5 tickets
- **P3 (Low)**: 3 tickets

### Herbie Integration Benefits

**Effort Reduction**:
- **TICKET-004**: Reduced from L (1-3 days) to M (4-8 hours) - 50% time savings
- **TICKET-005**: Reduced from S to XS - simplified to configuration only
- **TICKET-006**: Reduced from L (1-3 days) to M (4-8 hours) - cleaner xarray integration
- **Total Saved**: ~3-4 days of development time

**Technical Improvements**:
- ✅ Automatic byte-range downloads (no manual .idx parsing)
- ✅ Built-in retry logic and error handling
- ✅ Multi-source fallback (AWS → Google Cloud → NOMADS → Azure)
- ✅ Direct xarray integration (no intermediate GRIB2 files)
- ✅ Support for 15+ weather models (GFS, RAP, GEFS, ECMWF, etc.)
- ✅ FastHerbie for parallel bulk downloads
- ✅ Simplified variable selection (GRIB2 search strings vs band numbers)

**Future Scalability**:
- Easy to add new weather models (1-line change)
- Simple to add new variables (configuration-based)
- Built-in support for historical data archive
- Community-maintained package with regular updates

### Estimated Timeline (Updated with Herbie)

- **Phase 1-2** (Infrastructure + Ingestion): 4 days (reduced from 1 week)
- **Phase 3-4** (Processing + Tiles): 5 days (reduced from 1 week)
- **Phase 5-6** (Automation + Web): 1 week
- **Phase 7-9** (Monitoring + Docs): 3 days
- **Phase 10** (Future Enhancements): Ongoing

**Total Core Implementation**: ~2.5-3 weeks for one developer (reduced from 3-4 weeks)

### Dependencies Graph

```
TICKET-001 (Terraform)
    ↓
TICKET-002 (EC2) → TICKET-003 (Docker)
    ↓                    ↓
TICKET-004 (Download) ← TICKET-005 (Band ID)
    ↓
TICKET-006 (GDAL Processing) → TICKET-007 (Color Ramp)
    ↓
TICKET-008 (Tile Generation) → TICKET-009 (Optimization)
    ↓
TICKET-010 (Orchestration) → TICKET-012 (Metadata)
    ↓
TICKET-011 (Cron)
    ↓
TICKET-013 (Web App) → TICKET-014 (Animation)
    ↓
TICKET-015 (Deploy Web)
    ↓
TICKET-016 (Monitoring) → TICKET-017 (Alarms) → TICKET-018 (Dashboard)
    ↓
TICKET-019 (Testing) → TICKET-020 (Load Testing)
    ↓
TICKET-021 (Runbook) → TICKET-022 (Cost Review)
    ↓
TICKET-023, 024, 025 (Future Enhancements)
```

### Getting Started

1. Start with TICKET-001 to deploy infrastructure
2. Follow tickets in numerical order for optimal dependency resolution
3. Mark tickets complete when all acceptance criteria met
4. Update this document with actual completion dates and notes

---

**Project Status**: 🔴 Not Started (1 ticket partial: TICKET-001 has S3 bucket created)

**Last Updated**: 2026-01-09
