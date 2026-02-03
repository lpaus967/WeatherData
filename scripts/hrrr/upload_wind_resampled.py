#!/usr/bin/env python3
"""
HRRR Wind Data Resampling and Mapbox Upload Script

Downloads HRRR wind data (U/V components), resamples to 4x resolution,
and uploads to Mapbox as a raster-array tileset for wind particle visualization.

Tileset: onwaterllc.hrrr_wind_resampled

Requirements:
    pip install herbie-data xarray scipy rasterio numpy boto3 requests

Usage:
    python upload_wind_resampled.py --latest
    python upload_wind_resampled.py --date 2026-02-03 --cycle 12
"""

import argparse
import logging
import sys
import os
import json
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
import shutil

import numpy as np
import xarray as xr
from scipy.ndimage import zoom
from herbie import Herbie
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS

# Configuration
MAPBOX_USERNAME = "onwaterllc"
TILESET_NAME = "hrrr_wind_resampled"
TILESET_ID = f"{MAPBOX_USERNAME}.{TILESET_NAME}"
TEMP_DIR = Path("/tmp/wind-resampled")
SCALE_FACTOR = 4  # 4x upsampling (~3km -> ~750m)
MAX_ZOOM = 12  # Higher zoom for resampled data

# Mapbox access token (use environment variable)
MAPBOX_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "")


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger('wind_resampled')


def calculate_latest_forecast_time() -> datetime:
    """Calculate latest available HRRR forecast time (3 hours ago)."""
    now = datetime.utcnow()
    latest = now - timedelta(hours=3)
    latest = latest.replace(minute=0, second=0, microsecond=0)
    return latest


def download_wind_data(
    date: datetime,
    fxx: int,
    output_dir: Path,
    logger: logging.Logger
) -> Optional[xr.Dataset]:
    """
    Download HRRR wind data (U and V components) using Herbie.
    
    Args:
        date: Forecast initialization datetime
        fxx: Forecast hour
        output_dir: Directory for temporary files
        logger: Logger instance
    
    Returns:
        xarray Dataset with u10 and v10 components, or None if failed
    """
    try:
        logger.info(f"Downloading HRRR wind data: {date} F{fxx:02d}")
        
        H = Herbie(date, model='hrrr', product='sfc', fxx=fxx)
        
        # Download U and V wind components at 10m
        ds_u = H.xarray("UGRD:10 m", remove_grib=False)
        ds_v = H.xarray("VGRD:10 m", remove_grib=False)
        
        # Merge into single dataset
        ds = xr.merge([ds_u, ds_v])
        
        logger.info(f"Downloaded wind data: {ds.dims}")
        return ds
        
    except Exception as e:
        logger.error(f"Failed to download wind data: {e}")
        return None


def resample_wind_data(
    ds: xr.Dataset,
    scale_factor: int,
    logger: logging.Logger
) -> xr.Dataset:
    """
    Resample wind data to higher resolution using bilinear interpolation.
    
    Args:
        ds: Input xarray Dataset with u10 and v10
        scale_factor: Upsampling factor (e.g., 4 for 4x resolution)
        logger: Logger instance
    
    Returns:
        Resampled xarray Dataset
    """
    logger.info(f"Resampling wind data by {scale_factor}x...")
    
    # Get coordinate names (HRRR uses y/x or latitude/longitude)
    y_dim = 'y' if 'y' in ds.dims else 'latitude'
    x_dim = 'x' if 'x' in ds.dims else 'longitude'
    
    # Create new coordinates
    new_y = np.linspace(
        ds[y_dim].values[0],
        ds[y_dim].values[-1],
        len(ds[y_dim]) * scale_factor
    )
    new_x = np.linspace(
        ds[x_dim].values[0],
        ds[x_dim].values[-1],
        len(ds[x_dim]) * scale_factor
    )
    
    # Interpolate using xarray's built-in method
    ds_resampled = ds.interp(
        {y_dim: new_y, x_dim: new_x},
        method='linear'
    )
    
    logger.info(f"Resampled from {ds.dims} to {ds_resampled.dims}")
    return ds_resampled


def create_wind_geotiff(
    ds: xr.Dataset,
    output_path: Path,
    valid_time: datetime,
    logger: logging.Logger
) -> bool:
    """
    Create a multi-band GeoTIFF with U and V wind components.
    
    The GeoTIFF will have 2 bands:
    - Band 1: U component (east-west wind)
    - Band 2: V component (north-south wind)
    
    Args:
        ds: xarray Dataset with resampled wind data
        output_path: Output GeoTIFF path
        valid_time: Valid time for the forecast
        logger: Logger instance
    
    Returns:
        True if successful
    """
    try:
        # Get variable names (handle different naming conventions)
        u_var = 'u10' if 'u10' in ds else 'UGRD_10maboveground' if 'UGRD_10maboveground' in ds else list(ds.data_vars)[0]
        v_var = 'v10' if 'v10' in ds else 'VGRD_10maboveground' if 'VGRD_10maboveground' in ds else list(ds.data_vars)[1]
        
        u_data = ds[u_var].values
        v_data = ds[v_var].values
        
        # Handle 3D arrays (time dimension)
        if u_data.ndim == 3:
            u_data = u_data[0]
            v_data = v_data[0]
        
        # Get coordinate info
        y_dim = 'y' if 'y' in ds.dims else 'latitude'
        x_dim = 'x' if 'x' in ds.dims else 'longitude'
        
        y_coords = ds[y_dim].values
        x_coords = ds[x_dim].values
        
        # Calculate bounds
        # HRRR is in Lambert Conformal, but we'll convert to Web Mercator for Mapbox
        height, width = u_data.shape
        
        # Create transform
        transform = from_bounds(
            x_coords.min(), y_coords.min(),
            x_coords.max(), y_coords.max(),
            width, height
        )
        
        # Get CRS from dataset or default to Lambert Conformal
        try:
            crs = ds.rio.crs
            if crs is None:
                # HRRR Lambert Conformal Conic
                crs = CRS.from_proj4(
                    "+proj=lcc +lat_0=38.5 +lon_0=-97.5 +lat_1=38.5 +lat_2=38.5 "
                    "+x_0=0 +y_0=0 +R=6371229 +units=m +no_defs"
                )
        except:
            crs = CRS.from_epsg(4326)  # Fallback to WGS84
        
        # Stack U and V into 2 bands
        wind_data = np.stack([u_data, v_data], axis=0).astype(np.float32)
        
        # Write GeoTIFF
        profile = {
            'driver': 'GTiff',
            'dtype': 'float32',
            'width': width,
            'height': height,
            'count': 2,
            'crs': crs,
            'transform': transform,
            'compress': 'deflate',
            'tiled': True,
            'blockxsize': 256,
            'blockysize': 256,
        }
        
        # Add band metadata
        with rasterio.open(output_path, 'w', **profile) as dst:
            dst.write(wind_data)
            dst.set_band_description(1, 'u10')
            dst.set_band_description(2, 'v10')
            # Add valid time as tag
            dst.update_tags(
                GRIB_VALID_TIME=str(int(valid_time.timestamp()))
            )
        
        logger.info(f"Created GeoTIFF: {output_path} ({width}x{height}, 2 bands)")
        return True
        
    except Exception as e:
        logger.error(f"Failed to create GeoTIFF: {e}")
        import traceback
        traceback.print_exc()
        return False


def safe_decode(output: bytes) -> str:
    """Safely decode subprocess output, handling non-UTF-8 bytes."""
    try:
        return output.decode('utf-8')
    except UnicodeDecodeError:
        return output.decode('utf-8', errors='replace')


def upload_to_mapbox(
    geotiff_path: Path,
    tileset_id: str,
    valid_time: datetime,
    logger: logging.Logger
) -> bool:
    """
    Upload GeoTIFF to Mapbox using the Uploads API (for raster tilesets).
    
    The Uploads API is the correct method for raster/image data.
    The Tilesets CLI is for vector data (MTS).
    
    Args:
        geotiff_path: Path to the GeoTIFF
        tileset_id: Mapbox tileset ID (username.tileset_name)
        valid_time: Valid time for band naming
        logger: Logger instance
    
    Returns:
        True if successful
    """
    import requests
    import boto3
    from botocore.config import Config
    
    if not MAPBOX_TOKEN:
        logger.error("MAPBOX_ACCESS_TOKEN environment variable not set")
        return False
    
    try:
        # Step 1: Get temporary S3 credentials from Mapbox
        logger.info("Getting Mapbox upload credentials...")
        creds_url = f"https://api.mapbox.com/uploads/v1/{MAPBOX_USERNAME}/credentials?access_token={MAPBOX_TOKEN}"
        creds_resp = requests.get(creds_url)
        
        if creds_resp.status_code != 200:
            logger.error(f"Failed to get credentials: {creds_resp.status_code} - {creds_resp.text}")
            return False
        
        creds = creds_resp.json()
        logger.info(f"Got credentials for bucket: {creds['bucket']}")
        
        # Step 2: Upload GeoTIFF to Mapbox's S3 staging bucket
        logger.info(f"Uploading {geotiff_path.name} to S3 staging...")
        
        s3_client = boto3.client(
            's3',
            aws_access_key_id=creds['accessKeyId'],
            aws_secret_access_key=creds['secretAccessKey'],
            aws_session_token=creds['sessionToken'],
            region_name='us-east-1',
            config=Config(signature_version='s3v4')
        )
        
        file_size = geotiff_path.stat().st_size
        logger.info(f"File size: {file_size / 1024 / 1024:.2f} MB")
        
        s3_client.upload_file(
            str(geotiff_path),
            creds['bucket'],
            creds['key'],
            Callback=lambda bytes_transferred: None  # Could add progress here
        )
        
        logger.info("S3 upload complete")
        
        # Step 3: Create the upload job
        logger.info(f"Creating upload for tileset: {tileset_id}")
        upload_url = f"https://api.mapbox.com/uploads/v1/{MAPBOX_USERNAME}?access_token={MAPBOX_TOKEN}"
        
        upload_data = {
            'url': creds['url'],
            'tileset': tileset_id,
            'name': f'HRRR Wind {valid_time.strftime("%Y-%m-%d %H:%M")} UTC'
        }
        
        upload_resp = requests.post(upload_url, json=upload_data)
        
        if upload_resp.status_code not in [200, 201]:
            logger.error(f"Failed to create upload: {upload_resp.status_code} - {upload_resp.text}")
            return False
        
        upload_info = upload_resp.json()
        upload_id = upload_info.get('id')
        logger.info(f"Upload created: {upload_id}")
        
        # Step 4: Poll for completion
        logger.info("Waiting for processing...")
        import time
        status_url = f"https://api.mapbox.com/uploads/v1/{MAPBOX_USERNAME}/{upload_id}?access_token={MAPBOX_TOKEN}"
        
        for attempt in range(60):  # Max 5 minutes
            time.sleep(5)
            status_resp = requests.get(status_url)
            
            if status_resp.status_code != 200:
                logger.warning(f"Status check failed: {status_resp.status_code}")
                continue
            
            status = status_resp.json()
            progress = status.get('progress', 0)
            complete = status.get('complete', False)
            error = status.get('error')
            
            if error:
                logger.error(f"Upload failed: {error}")
                return False
            
            if complete:
                logger.info(f"✓ Upload complete! Tileset: {tileset_id}")
                return True
            
            logger.info(f"Processing: {int(progress * 100)}%")
        
        logger.error("Upload timed out after 5 minutes")
        return False
        
    except Exception as e:
        logger.error(f"Mapbox upload failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def upload_via_api(
    geotiff_path: Path,
    tileset_id: str,
    valid_time: datetime,
    logger: logging.Logger
) -> bool:
    """
    Alternative upload method using Mapbox API directly.
    
    For raster-array tilesets, we need the MTS (Mapbox Tilesets Service) API.
    """
    import requests
    
    try:
        # Step 1: Get upload credentials
        creds_url = f"https://api.mapbox.com/uploads/v1/{MAPBOX_USERNAME}/credentials?access_token={MAPBOX_TOKEN}"
        creds_resp = requests.get(creds_url)
        
        if creds_resp.status_code != 200:
            logger.error(f"Failed to get upload credentials: {creds_resp.text}")
            return False
        
        creds = creds_resp.json()
        
        # Step 2: Upload to S3 staging
        import boto3
        
        s3_client = boto3.client(
            's3',
            aws_access_key_id=creds['accessKeyId'],
            aws_secret_access_key=creds['secretAccessKey'],
            aws_session_token=creds['sessionToken'],
            region_name='us-east-1'
        )
        
        s3_client.upload_file(
            str(geotiff_path),
            creds['bucket'],
            creds['key']
        )
        
        logger.info("Uploaded to Mapbox staging")
        
        # Step 3: Create upload
        upload_url = f"https://api.mapbox.com/uploads/v1/{MAPBOX_USERNAME}?access_token={MAPBOX_TOKEN}"
        upload_data = {
            'url': creds['url'],
            'tileset': tileset_id,
            'name': 'HRRR Wind Resampled 4x'
        }
        
        upload_resp = requests.post(upload_url, json=upload_data)
        
        if upload_resp.status_code not in [200, 201]:
            logger.error(f"Failed to create upload: {upload_resp.text}")
            return False
        
        upload_info = upload_resp.json()
        logger.info(f"Upload created: {upload_info.get('id')}")
        
        return True
        
    except Exception as e:
        logger.error(f"API upload failed: {e}")
        return False


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Resample HRRR wind data and upload to Mapbox'
    )
    
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument('--date', type=str, help='Forecast date (YYYY-MM-DD)')
    date_group.add_argument('--latest', action='store_true', help='Use latest forecast')
    
    parser.add_argument('--cycle', type=int, help='Model cycle hour (0-23)')
    parser.add_argument('--fxx', type=str, default='0', help='Forecast hours (e.g., "0-6")')
    parser.add_argument('--scale', type=int, default=SCALE_FACTOR, help=f'Resample scale factor (default: {SCALE_FACTOR})')
    parser.add_argument('--output-dir', type=Path, default=TEMP_DIR, help='Output directory')
    parser.add_argument('--keep-files', action='store_true', help='Keep intermediate files')
    parser.add_argument('--skip-upload', action='store_true', help='Skip Mapbox upload')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    logger = setup_logging(args.verbose)
    
    logger.info("=" * 60)
    logger.info("HRRR Wind Resampling Pipeline")
    logger.info("=" * 60)
    
    # Determine forecast date/time
    if args.latest:
        forecast_date = calculate_latest_forecast_time()
    else:
        if args.cycle is None:
            logger.error("--cycle required with --date")
            return 1
        forecast_date = datetime.strptime(f"{args.date} {args.cycle:02d}", "%Y-%m-%d %H")
    
    logger.info(f"Forecast: {forecast_date.strftime('%Y-%m-%d %H:00 UTC')}")
    logger.info(f"Scale factor: {args.scale}x")
    
    # Parse forecast hours
    fxx_list = []
    for part in args.fxx.split(','):
        if '-' in part:
            start, end = map(int, part.split('-'))
            fxx_list.extend(range(start, end + 1))
        else:
            fxx_list.append(int(part))
    
    logger.info(f"Forecast hours: {fxx_list}")
    
    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Process each forecast hour
    success_count = 0
    for fxx in fxx_list:
        logger.info(f"\n{'=' * 40}")
        logger.info(f"Processing F{fxx:02d}")
        logger.info(f"{'=' * 40}")
        
        # Calculate valid time
        valid_time = forecast_date + timedelta(hours=fxx)
        
        # Download wind data
        ds = download_wind_data(forecast_date, fxx, args.output_dir, logger)
        if ds is None:
            continue
        
        # Resample
        ds_resampled = resample_wind_data(ds, args.scale, logger)
        
        # Create GeoTIFF
        geotiff_name = f"wind_resampled_{forecast_date.strftime('%Y%m%d_%H')}z_f{fxx:02d}.tif"
        geotiff_path = args.output_dir / geotiff_name
        
        if not create_wind_geotiff(ds_resampled, geotiff_path, valid_time, logger):
            continue
        
        # Upload to Mapbox
        if not args.skip_upload:
            if upload_to_mapbox(geotiff_path, TILESET_ID, valid_time, logger):
                success_count += 1
        else:
            logger.info("Skipping Mapbox upload (--skip-upload)")
            success_count += 1
        
        # Cleanup
        if not args.keep_files and geotiff_path.exists():
            geotiff_path.unlink()
    
    # Summary
    logger.info(f"\n{'=' * 60}")
    logger.info("Summary")
    logger.info(f"{'=' * 60}")
    logger.info(f"Processed: {len(fxx_list)} forecast hours")
    logger.info(f"Successful: {success_count}")
    
    if not args.keep_files and args.output_dir.exists():
        shutil.rmtree(args.output_dir, ignore_errors=True)
    
    return 0 if success_count > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
