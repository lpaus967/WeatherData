#!/usr/bin/env python3
"""
HRRR Wind Data Resampling and Mapbox Upload Script

Downloads HRRR wind data, resamples to higher resolution, clips to region,
and uploads to Mapbox as a rasterarray tileset.

Based on working upload pattern from Wind pipeline.

Requirements:
    pip install herbie-data xarray scipy numpy requests

Usage:
    python upload_wind_resampled.py --latest
    python upload_wind_resampled.py --date 2026-02-03 --cycle 12
    python upload_wind_resampled.py --latest --region vermont
"""

import argparse
import logging
import sys
import os
import json
import subprocess
import tempfile
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List
import shutil
import requests

import numpy as np

# Configuration
MAPBOX_USERNAME = "onwaterllc"
TILESET_NAME = "hrrr_wind_resampled"
TILESET_ID = f"{MAPBOX_USERNAME}.{TILESET_NAME}"
TEMP_DIR = Path("/tmp/wind-resampled")
SCALE_FACTOR = 4  # 4x upsampling (~3km -> ~750m)

# Region bounding boxes (WGS84)
REGIONS = {
    'vermont': {
        'west': -73.54,
        'east': -71.37,
        'south': 42.63,
        'north': 45.12,
        'buffer': 0.1
    },
    'conus': None  # Full CONUS, no clipping
}

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


def download_hrrr_grib(
    date: datetime,
    fxx: int,
    output_dir: Path,
    logger: logging.Logger
) -> Optional[Path]:
    """
    Download HRRR GRIB2 file using Herbie.
    
    Returns path to downloaded GRIB file.
    """
    try:
        from herbie import Herbie
        
        logger.info(f"Downloading HRRR GRIB: {date} F{fxx:02d}")
        
        H = Herbie(date, model='hrrr', product='sfc', fxx=fxx)
        
        # Download the full file (we'll extract wind bands)
        grib_path = H.download(searchString="UGRD:10 m|VGRD:10 m")
        
        if grib_path and Path(grib_path).exists():
            logger.info(f"Downloaded: {grib_path}")
            return Path(grib_path)
        else:
            logger.error("Download returned no path")
            return None
            
    except Exception as e:
        logger.error(f"Failed to download HRRR: {e}")
        return None


def extract_wind_bands(
    input_grib: Path,
    output_dir: Path,
    logger: logging.Logger
) -> Optional[Path]:
    """
    Extract U and V wind bands from HRRR GRIB file.
    
    Uses gdal_translate to extract only the 10m wind components.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{input_grib.stem}_wind.grib2"
    
    # Fix PROJ database conflicts (Anaconda vs system GDAL)
    env = os.environ.copy()
    env.pop('PROJ_LIB', None)
    env.pop('PROJ_DATA', None)
    
    # First, find the correct band numbers for 10m U and V wind
    # Use gdalinfo to inspect the file
    try:
        result = subprocess.run(
            ['gdalinfo', str(input_grib)],
            capture_output=True,
            text=True,
            timeout=60,
            env=env
        )
        
        if result.returncode != 0:
            logger.error(f"gdalinfo failed: {result.stderr}")
            return None
        
        # Parse output to find U and V wind bands at 10m
        lines = result.stdout.split('\n')
        u_band = None
        v_band = None
        current_band = None
        
        for line in lines:
            if line.startswith('Band '):
                current_band = int(line.split()[1])
            elif 'GRIB_COMMENT=u-component of wind' in line and '10 m' in result.stdout[result.stdout.find(f'Band {current_band}'):result.stdout.find(f'Band {current_band + 1}') if current_band else len(result.stdout)]:
                u_band = current_band
            elif 'GRIB_COMMENT=v-component of wind' in line:
                v_band = current_band
        
        # Fallback: use bands 1 and 2 if we downloaded filtered data
        if u_band is None:
            u_band = 1
        if v_band is None:
            v_band = 2
            
        logger.info(f"Extracting bands: U={u_band}, V={v_band}")
        
        # Extract the bands
        cmd = [
            'gdal_translate',
            '-of', 'GRIB',
            '-b', str(u_band),
            '-b', str(v_band),
            str(input_grib),
            str(output_file)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        
        if result.returncode != 0:
            logger.error(f"gdal_translate failed: {result.stderr}")
            return None
        
        logger.info(f"Extracted wind bands: {output_file}")
        return output_file
        
    except Exception as e:
        logger.error(f"Failed to extract wind bands: {e}")
        return None


def clip_and_resample_grib(
    input_grib: Path,
    output_dir: Path,
    region: Optional[Dict],
    scale_factor: int,
    logger: logging.Logger
) -> Optional[Path]:
    """
    Clip to region and resample GRIB file to higher resolution.
    
    Uses gdalwarp for reprojection and resampling.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    region_name = "clipped" if region else "full"
    output_file = output_dir / f"{input_grib.stem}_{region_name}_resampled.grib2"
    
    try:
        # Build gdalwarp command
        cmd = [
            'gdalwarp',
            '-of', 'GRIB',
            '-r', 'bilinear',  # Bilinear resampling for smooth wind fields
        ]
        
        # Fix PROJ database conflicts (Anaconda vs system GDAL)
        env = os.environ.copy()
        env.pop('PROJ_LIB', None)  # Remove Anaconda's PROJ path
        env.pop('PROJ_DATA', None)
        
        # Add clipping bounds if region specified
        if region:
            west = region['west'] - region.get('buffer', 0)
            east = region['east'] + region.get('buffer', 0)
            south = region['south'] - region.get('buffer', 0)
            north = region['north'] + region.get('buffer', 0)
            
            cmd.extend([
                '-t_srs', 'EPSG:4326',  # Output in WGS84
                '-te', str(west), str(south), str(east), str(north),
            ])
            
            logger.info(f"Clipping to bounds: [{west}, {south}, {east}, {north}]")
        
        # Calculate output resolution (scale_factor x finer)
        # HRRR is ~3km, so 4x gives ~750m
        # For a regional clip, estimate pixels based on bounds
        if region:
            # Roughly 3km = 0.027 degrees at mid-latitudes
            base_res = 0.027
            new_res = base_res / scale_factor
            cmd.extend(['-tr', str(new_res), str(new_res)])
            logger.info(f"Resampling to {new_res:.4f} degree resolution ({scale_factor}x)")
        
        cmd.extend([str(input_grib), str(output_file)])
        
        logger.info(f"Running gdalwarp...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
        
        if result.returncode != 0:
            logger.error(f"gdalwarp failed: {result.stderr}")
            return None
        
        logger.info(f"Created resampled GRIB: {output_file}")
        return output_file
        
    except Exception as e:
        logger.error(f"Failed to clip/resample: {e}")
        return None


class MapboxUploader:
    """Handle Mapbox MTS rasterarray tileset uploads."""
    
    def __init__(self, username: str, tileset_name: str, token: str, logger: logging.Logger):
        self.username = username
        self.tileset_name = tileset_name
        self.tileset_id = f"{username}.{tileset_name}"
        self.token = token
        self.logger = logger
    
    async def delete_tileset_source(self) -> bool:
        """Delete existing tileset source."""
        self.logger.info(f"Deleting tileset-source: {self.tileset_id}")
        url = f"https://api.mapbox.com/tilesets/v1/sources/{self.username}/{self.tileset_name}?access_token={self.token}"
        
        try:
            response = requests.delete(url)
            if response.ok or response.status_code == 404:
                self.logger.info("✓ Source deleted (or didn't exist)")
                return True
            else:
                self.logger.error(f"Failed to delete source: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"Error deleting source: {e}")
            return False
    
    async def upload_files_to_source(self, grib_files: List[Path], replace: bool = True) -> bool:
        """Upload GRIB files to tileset source using multipart upload."""
        if not grib_files:
            self.logger.error("No files to upload")
            return False
        
        self.logger.info(f"Uploading {len(grib_files)} file(s) to source...")
        
        if replace:
            if not await self.delete_tileset_source():
                return False
            # Wait for deletion to complete
            self.logger.info("Waiting for source deletion to complete...")
            await asyncio.sleep(10)
        
        url = f"https://api.mapbox.com/tilesets/v1/sources/{self.username}/{self.tileset_name}?access_token={self.token}"
        
        try:
            files = []
            file_handles = []
            for grib_file in grib_files:
                fh = open(grib_file, 'rb')
                file_handles.append(fh)
                files.append(('file', (grib_file.name, fh, 'application/octet-stream')))
            
            response = requests.post(url, files=files)
            
            # Close file handles
            for fh in file_handles:
                fh.close()
            
            if response.ok:
                self.logger.info(f"✓ Uploaded {len(grib_files)} file(s)")
                return True
            else:
                self.logger.error(f"Upload failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"Upload error: {e}")
            return False
    
    def create_recipe(self, output_path: Path, use_dynamic_bands: bool = False) -> Path:
        """
        Create Mapbox rasterarray recipe.
        
        Args:
            output_path: Path to save the recipe JSON
            use_dynamic_bands: If True, uses Band_1, Band_2, etc. instead of GRIB_VALID_TIME
                              This makes the front-end code not need daily updates!
        """
        if use_dynamic_bands:
            # Dynamic band naming - no need to update React code daily!
            name_expression = [
                "concat",
                "Band_",
                [
                    "to-string",
                    ["+", 1, ["index-of", ["get", "GRIB_VALID_TIME"], ["array"]]]
                ]
            ]
        else:
            # Original: Uses actual GRIB_VALID_TIME (requires React updates)
            name_expression = ["to-number", ["get", "GRIB_VALID_TIME"]]
        
        recipe = {
            "version": 1,
            "type": "rasterarray",
            "sources": [
                {"uri": f"mapbox://tileset-source/{self.username}/{self.tileset_name}"}
            ],
            "layers": {
                "wind10m": {
                    "tilesize": 512,
                    "resampling": "bilinear",
                    "minzoom": 0,
                    "maxzoom": 12,  # Higher zoom for resampled data
                    "source_rules": {
                        "name": name_expression,
                        "sort_key": ["to-number", ["get", "GRIB_VALID_TIME"]],
                        "order": "asc",
                        "filter": [
                            [
                                "all",
                                ["==", ["get", "GRIB_COMMENT"], "u-component of wind [m/s]"],
                                ["==", ["get", "GRIB_SHORT_NAME"], "10-HTGL"]
                            ],
                            [
                                "all",
                                ["==", ["get", "GRIB_COMMENT"], "v-component of wind [m/s]"],
                                ["==", ["get", "GRIB_SHORT_NAME"], "10-HTGL"]
                            ]
                        ]
                    }
                }
            }
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(recipe, f, indent=2)
        
        self.logger.info(f"✓ Created recipe: {output_path}")
        return output_path
    
    async def create_or_update_tileset(self, recipe_path: Path) -> bool:
        """Create tileset or update its recipe."""
        # Try to update first
        update_url = f"https://api.mapbox.com/tilesets/v1/{self.tileset_id}/recipe?access_token={self.token}"
        
        with open(recipe_path, 'r') as f:
            recipe = json.load(f)
        
        response = requests.patch(
            update_url,
            headers={'Content-Type': 'application/json'},
            json=recipe
        )
        
        if response.ok:
            self.logger.info("✓ Recipe updated")
            return True
        
        # Try to create if update failed
        self.logger.info("Creating new tileset...")
        create_url = f"https://api.mapbox.com/tilesets/v1/{self.tileset_id}?access_token={self.token}"
        
        response = requests.post(
            create_url,
            headers={'Content-Type': 'application/json'},
            json={"recipe": recipe, "name": self.tileset_name}
        )
        
        if response.ok or response.status_code == 409:
            self.logger.info("✓ Tileset created/exists")
            return True
        else:
            self.logger.error(f"Failed to create tileset: {response.status_code} - {response.text}")
            return False
    
    async def publish(self) -> bool:
        """Publish the tileset."""
        self.logger.info(f"Publishing tileset: {self.tileset_id}")
        url = f"https://api.mapbox.com/tilesets/v1/{self.tileset_id}/publish?access_token={self.token}"
        
        response = requests.post(url)
        
        if response.ok:
            self.logger.info("✓ Publish job started")
            return True
        else:
            self.logger.error(f"Publish failed: {response.status_code} - {response.text}")
            return False
    
    async def check_status(self) -> None:
        """Check tileset job status."""
        url = f"https://api.mapbox.com/tilesets/v1/{self.tileset_id}/jobs?limit=1&access_token={self.token}"
        response = requests.get(url)
        if response.ok:
            self.logger.info(f"Job status: {response.text}")


async def upload_to_mapbox(
    grib_files: List[Path],
    tileset_name: str,
    logger: logging.Logger,
    use_dynamic_bands: bool = False
) -> bool:
    """
    Upload processed GRIB files to Mapbox as rasterarray tileset.
    
    Args:
        grib_files: List of GRIB files to upload
        tileset_name: Name of the Mapbox tileset
        logger: Logger instance
        use_dynamic_bands: If True, uses Band_1, Band_2, etc. for stable band names
    """
    if not MAPBOX_TOKEN:
        logger.error("MAPBOX_ACCESS_TOKEN not set")
        return False
    
    uploader = MapboxUploader(MAPBOX_USERNAME, tileset_name, MAPBOX_TOKEN, logger)
    
    # Create recipe
    recipe_path = TEMP_DIR / "recipe.json"
    uploader.create_recipe(recipe_path, use_dynamic_bands=use_dynamic_bands)
    
    # Upload files
    if not await uploader.upload_files_to_source(grib_files, replace=True):
        return False
    
    # Wait for upload to be processed
    logger.info("Waiting for source upload to be processed...")
    await asyncio.sleep(10)
    
    # Create/update tileset
    if not await uploader.create_or_update_tileset(recipe_path):
        return False
    
    # Wait for recipe update to complete
    logger.info("Waiting for recipe update to complete...")
    await asyncio.sleep(15)
    
    # Publish
    if not await uploader.publish():
        return False
    
    # Wait for publish to start
    logger.info("Waiting for tileset publish to start...")
    await asyncio.sleep(20)
    await uploader.check_status()
    
    logger.info(f"\n✓ Tileset available at: mapbox://{MAPBOX_USERNAME}.{tileset_name}")
    return True


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Resample HRRR wind data and upload to Mapbox'
    )
    
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument('--date', type=str, help='Forecast date (YYYY-MM-DD)')
    date_group.add_argument('--latest', action='store_true', help='Use latest forecast')
    
    parser.add_argument('--cycle', type=int, help='Model cycle hour (0-23)')
    parser.add_argument('--fxx', type=str, default='0', help='Forecast hours (e.g., "0-6" or "0,3,6")')
    parser.add_argument('--scale', type=int, default=SCALE_FACTOR, help=f'Resample scale (default: {SCALE_FACTOR})')
    parser.add_argument('--region', type=str, choices=list(REGIONS.keys()), default='vermont', help='Region to clip')
    parser.add_argument('--tileset', type=str, default=TILESET_NAME, help='Mapbox tileset name')
    parser.add_argument('--output-dir', type=Path, default=TEMP_DIR, help='Output directory')
    parser.add_argument('--keep-files', action='store_true', help='Keep intermediate files')
    parser.add_argument('--skip-upload', action='store_true', help='Skip Mapbox upload')
    parser.add_argument('--dynamic-bands', action='store_true', 
                        help='Use Band_1, Band_2, etc. instead of timestamps (no frontend updates needed)')
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
    logger.info(f"Region: {args.region}")
    logger.info(f"Scale: {args.scale}x")
    
    # Parse forecast hours
    fxx_list = []
    for part in args.fxx.split(','):
        if '-' in part:
            start, end = map(int, part.split('-'))
            fxx_list.extend(range(start, end + 1))
        else:
            fxx_list.append(int(part))
    
    logger.info(f"Forecast hours: {fxx_list}")
    
    # Create directories
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output_dir / "raw"
    extracted_dir = args.output_dir / "extracted"
    resampled_dir = args.output_dir / "resampled"
    
    region = REGIONS.get(args.region)
    processed_files = []
    
    for fxx in fxx_list:
        logger.info(f"\n{'=' * 40}")
        logger.info(f"Processing F{fxx:02d}")
        logger.info(f"{'=' * 40}")
        
        # Download
        grib_path = download_hrrr_grib(forecast_date, fxx, raw_dir, logger)
        if not grib_path:
            continue
        
        # Extract wind bands
        extracted_path = extract_wind_bands(grib_path, extracted_dir, logger)
        if not extracted_path:
            continue
        
        # Clip and resample
        resampled_path = clip_and_resample_grib(
            extracted_path, resampled_dir, region, args.scale, logger
        )
        if resampled_path:
            processed_files.append(resampled_path)
    
    # Upload to Mapbox
    if processed_files and not args.skip_upload:
        logger.info(f"\n{'=' * 60}")
        logger.info("Uploading to Mapbox")
        logger.info(f"{'=' * 60}")
        
        success = asyncio.run(upload_to_mapbox(
            processed_files, 
            args.tileset, 
            logger,
            use_dynamic_bands=args.dynamic_bands
        ))
        
        if not success:
            logger.error("Upload failed")
            return 1
    
    # Cleanup
    if not args.keep_files:
        shutil.rmtree(args.output_dir, ignore_errors=True)
    
    logger.info("\n✓ Pipeline complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
