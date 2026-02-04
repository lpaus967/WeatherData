#!/usr/bin/env python3
"""
TBOFS (Tampa Bay Operational Forecast System) Download Script

Downloads ocean temperature and current data from NOAA NOMADS.
TBOFS provides high-resolution (~100m) coastal forecasts for Tampa Bay.

Data source: https://nomads.ncep.noaa.gov/pub/data/nccf/com/nosofs/prod/

Variables:
    - temp: Sea water temperature (°C)
    - u: Eastward current velocity (m/s)
    - v: Northward current velocity (m/s)
    - zeta: Water surface elevation (m)

Requirements:
    pip install requests xarray netCDF4 numpy

Usage:
    python download_tbofs.py --latest
    python download_tbofs.py --date 2026-02-04 --cycle 00
    python download_tbofs.py --latest --hours 0-6  # Only first 6 forecast hours
"""

import argparse
import logging
import sys
import os
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
BASE_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/nosofs/prod"
MODEL = "tbofs"
DEFAULT_OUTPUT_DIR = Path("/tmp/tbofs-data")

# TBOFS runs 4 times daily: 00, 06, 12, 18 UTC
VALID_CYCLES = [0, 6, 12, 18]


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger('tbofs_download')


def get_latest_cycle() -> Tuple[datetime, int]:
    """
    Determine the latest available TBOFS cycle.
    
    TBOFS runs at 00, 06, 12, 18 UTC with ~1-2 hour delay.
    
    Returns:
        Tuple of (date, cycle_hour)
    """
    now = datetime.utcnow()
    
    # Account for processing delay (~2 hours)
    available_time = now - timedelta(hours=2)
    
    # Find the most recent valid cycle
    hour = available_time.hour
    cycle = max([c for c in VALID_CYCLES if c <= hour], default=18)
    
    # If we wrapped to previous day's 18Z
    if cycle > hour:
        available_time -= timedelta(days=1)
    
    date = available_time.replace(hour=0, minute=0, second=0, microsecond=0)
    
    return date, cycle


def check_data_available(date: datetime, cycle: int, logger: logging.Logger) -> bool:
    """Check if TBOFS data is available for the given date/cycle."""
    date_str = date.strftime("%Y%m%d")
    url = f"{BASE_URL}/{MODEL}.{date_str}/{MODEL}.t{cycle:02d}z.{date_str}.fields.f001.nc"
    
    try:
        response = requests.head(url, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.warning(f"Could not check availability: {e}")
        return False


def download_file(url: str, output_path: Path, logger: logging.Logger) -> bool:
    """Download a single file with progress indication."""
    try:
        response = requests.get(url, stream=True, timeout=300)
        
        if response.status_code == 404:
            logger.warning(f"File not found: {url}")
            return False
        
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        
        with open(output_path, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
        
        logger.info(f"✓ Downloaded: {output_path.name} ({total_size / 1024 / 1024:.1f} MB)")
        return True
        
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        if output_path.exists():
            output_path.unlink()
        return False


def download_tbofs(
    date: datetime,
    cycle: int,
    forecast_hours: List[int],
    output_dir: Path,
    include_nowcast: bool,
    max_workers: int,
    logger: logging.Logger
) -> List[Path]:
    """
    Download TBOFS NetCDF files.
    
    Args:
        date: Forecast date
        cycle: Model cycle (0, 6, 12, 18)
        forecast_hours: List of forecast hours to download
        output_dir: Output directory
        include_nowcast: Include nowcast (analysis) files
        max_workers: Number of parallel downloads
        logger: Logger instance
    
    Returns:
        List of downloaded file paths
    """
    date_str = date.strftime("%Y%m%d")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Build list of files to download
    files_to_download = []
    
    # Forecast files
    for fxx in forecast_hours:
        filename = f"{MODEL}.t{cycle:02d}z.{date_str}.fields.f{fxx:03d}.nc"
        url = f"{BASE_URL}/{MODEL}.{date_str}/{filename}"
        output_path = output_dir / filename
        files_to_download.append((url, output_path))
    
    # Nowcast files (n001-n006 typically)
    if include_nowcast:
        for n in range(1, 7):
            filename = f"{MODEL}.t{cycle:02d}z.{date_str}.fields.n{n:03d}.nc"
            url = f"{BASE_URL}/{MODEL}.{date_str}/{filename}"
            output_path = output_dir / filename
            files_to_download.append((url, output_path))
    
    logger.info(f"Downloading {len(files_to_download)} files...")
    
    downloaded_files = []
    
    # Download in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_file, url, path, logger): path
            for url, path in files_to_download
        }
        
        for future in as_completed(futures):
            path = futures[future]
            try:
                if future.result():
                    downloaded_files.append(path)
            except Exception as e:
                logger.error(f"Download failed: {e}")
    
    return sorted(downloaded_files)


def inspect_netcdf(file_path: Path, logger: logging.Logger) -> None:
    """Inspect a NetCDF file and print variable info."""
    try:
        import xarray as xr
        
        ds = xr.open_dataset(file_path)
        
        logger.info(f"\nNetCDF Structure: {file_path.name}")
        logger.info(f"Dimensions: {dict(ds.dims)}")
        logger.info(f"Coordinates: {list(ds.coords)}")
        logger.info(f"Variables:")
        
        for var in ds.data_vars:
            v = ds[var]
            logger.info(f"  {var}: {v.dims} - {v.attrs.get('long_name', 'N/A')}")
        
        ds.close()
        
    except ImportError:
        logger.warning("xarray not installed, skipping inspection")
    except Exception as e:
        logger.error(f"Could not inspect file: {e}")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Download TBOFS ocean forecast data from NOMADS'
    )
    
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument('--date', type=str, help='Forecast date (YYYY-MM-DD)')
    date_group.add_argument('--latest', action='store_true', help='Use latest available')
    
    parser.add_argument('--cycle', type=int, choices=VALID_CYCLES,
                        help='Model cycle hour (0, 6, 12, 18)')
    parser.add_argument('--hours', type=str, default='1-48',
                        help='Forecast hours range (e.g., "1-48" or "1,6,12,24")')
    parser.add_argument('--output-dir', '-o', type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f'Output directory (default: {DEFAULT_OUTPUT_DIR})')
    parser.add_argument('--nowcast', action='store_true',
                        help='Include nowcast (analysis) files')
    parser.add_argument('--workers', type=int, default=4,
                        help='Number of parallel downloads (default: 4)')
    parser.add_argument('--inspect', action='store_true',
                        help='Inspect downloaded NetCDF structure')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose logging')
    
    args = parser.parse_args()
    logger = setup_logging(args.verbose)
    
    logger.info("=" * 60)
    logger.info("TBOFS Data Download")
    logger.info("=" * 60)
    
    # Determine date and cycle
    if args.latest:
        date, cycle = get_latest_cycle()
        logger.info(f"Latest available: {date.strftime('%Y-%m-%d')} {cycle:02d}Z")
    else:
        date = datetime.strptime(args.date, "%Y-%m-%d")
        cycle = args.cycle
        if cycle is None:
            logger.error("--cycle required with --date")
            return 1
    
    # Check availability
    if not check_data_available(date, cycle, logger):
        logger.warning(f"Data may not be available for {date.strftime('%Y-%m-%d')} {cycle:02d}Z")
        # Try previous cycle
        if args.latest:
            prev_cycle_idx = VALID_CYCLES.index(cycle) - 1
            if prev_cycle_idx >= 0:
                cycle = VALID_CYCLES[prev_cycle_idx]
            else:
                date -= timedelta(days=1)
                cycle = 18
            logger.info(f"Trying: {date.strftime('%Y-%m-%d')} {cycle:02d}Z")
    
    # Parse forecast hours
    forecast_hours = []
    for part in args.hours.split(','):
        if '-' in part:
            start, end = map(int, part.split('-'))
            forecast_hours.extend(range(start, end + 1))
        else:
            forecast_hours.append(int(part))
    
    logger.info(f"Date: {date.strftime('%Y-%m-%d')}")
    logger.info(f"Cycle: {cycle:02d}Z")
    logger.info(f"Forecast hours: {min(forecast_hours)}-{max(forecast_hours)} ({len(forecast_hours)} files)")
    logger.info(f"Output: {args.output_dir}")
    
    # Download files
    downloaded = download_tbofs(
        date=date,
        cycle=cycle,
        forecast_hours=forecast_hours,
        output_dir=args.output_dir,
        include_nowcast=args.nowcast,
        max_workers=args.workers,
        logger=logger
    )
    
    # Summary
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Download Summary")
    logger.info(f"{'=' * 60}")
    logger.info(f"Downloaded: {len(downloaded)} files")
    logger.info(f"Location: {args.output_dir}")
    
    # Inspect first file
    if args.inspect and downloaded:
        inspect_netcdf(downloaded[0], logger)
    
    return 0 if downloaded else 1


if __name__ == '__main__':
    sys.exit(main())
