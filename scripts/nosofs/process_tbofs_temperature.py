#!/usr/bin/env python3
"""
TBOFS Temperature Processing Script

Extracts sea surface temperature from TBOFS NetCDF files and creates
colored GeoTIFFs suitable for tile generation and S3 upload.

Requirements:
    pip install xarray netCDF4 numpy rasterio matplotlib

Usage:
    python process_tbofs_temperature.py --input-dir /tmp/tbofs-data --output-dir /tmp/tbofs-temp
"""

import argparse
import logging
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple
import numpy as np

try:
    import xarray as xr
    XARRAY_AVAILABLE = True
except ImportError:
    XARRAY_AVAILABLE = False

try:
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.crs import CRS
    RASTERIO_AVAILABLE = True
except ImportError:
    RASTERIO_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger('tbofs_temp')


# Temperature colormap (Celsius) - similar to ocean temperature charts
# Blue (cold) -> Cyan -> Green -> Yellow -> Orange -> Red (warm)
TEMP_COLORS = [
    (0, '#08306b'),    # Dark blue - very cold
    (10, '#2171b5'),   # Blue
    (15, '#4eb3d3'),   # Cyan
    (20, '#7fcdbb'),   # Light cyan-green
    (24, '#c7e9b4'),   # Light green
    (26, '#ffffb2'),   # Yellow
    (28, '#fecc5c'),   # Light orange
    (30, '#fd8d3c'),   # Orange
    (32, '#f03b20'),   # Red-orange
    (35, '#bd0026'),   # Dark red - very warm
]


def create_colormap():
    """Create a temperature colormap."""
    temps = [t[0] for t in TEMP_COLORS]
    colors = [t[1] for t in TEMP_COLORS]
    
    # Normalize temperatures to 0-1 range
    min_temp, max_temp = min(temps), max(temps)
    norm_temps = [(t - min_temp) / (max_temp - min_temp) for t in temps]
    
    # Convert hex colors to RGB
    rgb_colors = []
    for c in colors:
        c = c.lstrip('#')
        rgb_colors.append(tuple(int(c[i:i+2], 16) / 255.0 for i in (0, 2, 4)))
    
    cmap = LinearSegmentedColormap.from_list(
        'ocean_temp',
        list(zip(norm_temps, rgb_colors))
    )
    
    return cmap, min_temp, max_temp


def extract_sst(
    nc_file: Path,
    output_dir: Path,
    colorize: bool,
    logger: logging.Logger
) -> Optional[Tuple[Path, Optional[Path]]]:
    """
    Extract sea surface temperature from TBOFS NetCDF.
    
    Args:
        nc_file: Input NetCDF file
        output_dir: Output directory
        colorize: Create colored version for visualization
        logger: Logger instance
    
    Returns:
        Tuple of (data_tif_path, colored_tif_path) or None if failed
    """
    if not XARRAY_AVAILABLE or not RASTERIO_AVAILABLE:
        logger.error("Required packages missing")
        return None
    
    try:
        ds = xr.open_dataset(nc_file)
        
        # Find time
        if 'ocean_time' in ds:
            time_var = ds['ocean_time']
            if hasattr(time_var, 'values') and len(time_var.values) > 0:
                valid_time = time_var.values[0]
                if hasattr(valid_time, 'astype'):
                    valid_timestamp = int(valid_time.astype('datetime64[s]').astype('int64'))
                else:
                    valid_timestamp = int(datetime.utcnow().timestamp())
            else:
                valid_timestamp = int(datetime.utcnow().timestamp())
        else:
            valid_timestamp = int(datetime.utcnow().timestamp())
        
        logger.info(f"Processing: {nc_file.name}")
        logger.info(f"Valid time: {datetime.utcfromtimestamp(valid_timestamp)}")
        
        # Find temperature variable
        temp_var = None
        temp_names = ['temp', 'temperature', 'water_temp', 'sea_water_temperature', 'sst']
        
        for name in temp_names:
            if name in ds:
                temp_var = name
                break
        
        if temp_var is None:
            logger.error(f"Could not find temperature variable. Available: {list(ds.data_vars)}")
            ds.close()
            return None
        
        logger.info(f"Using variable: {temp_var}")
        
        # Extract data
        temp_data = ds[temp_var]
        
        # Get surface layer
        if 's_rho' in temp_data.dims:
            temp_surface = temp_data.isel(s_rho=-1)
        elif 'Nz' in temp_data.dims:
            temp_surface = temp_data.isel(Nz=-1)
        else:
            temp_surface = temp_data
        
        # Squeeze time dimension
        if 'ocean_time' in temp_surface.dims:
            temp_surface = temp_surface.isel(ocean_time=0)
        
        # Get coordinates
        if 'lon_rho' in ds:
            lon = ds['lon_rho'].values
            lat = ds['lat_rho'].values
        elif 'Longitude' in ds:
            lon = ds['Longitude'].values
            lat = ds['Latitude'].values
        else:
            logger.error("Could not find coordinate variables")
            ds.close()
            return None
        
        # Get data as numpy array
        temp_values = temp_surface.values.astype(np.float32)
        
        # Handle masked values
        if hasattr(temp_values, 'filled'):
            temp_values = temp_values.filled(np.nan)
        
        # Replace fill values
        temp_values = np.where(np.abs(temp_values) > 100, np.nan, temp_values)
        
        # Check units - convert Kelvin to Celsius if needed
        valid_temps = temp_values[~np.isnan(temp_values)]
        if len(valid_temps) > 0 and np.mean(valid_temps) > 200:
            logger.info("Converting from Kelvin to Celsius")
            temp_values = temp_values - 273.15
        
        logger.info(f"Grid shape: {temp_values.shape}")
        logger.info(f"Temperature range: {np.nanmin(temp_values):.1f}°C to {np.nanmax(temp_values):.1f}°C")
        
        # Calculate bounds
        if lon.ndim == 2:
            lon_min, lon_max = float(np.nanmin(lon)), float(np.nanmax(lon))
            lat_min, lat_max = float(np.nanmin(lat)), float(np.nanmax(lat))
        else:
            lon_min, lon_max = float(lon.min()), float(lon.max())
            lat_min, lat_max = float(lat.min()), float(lat.max())
        
        ds.close()
        
        # Create output directories
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract forecast info from filename
        stem = nc_file.stem
        if '.fields.' in stem:
            forecast_part = stem.split('.fields.')[-1]
        else:
            forecast_part = "f000"
        
        height, width = temp_values.shape
        transform = from_bounds(lon_min, lat_min, lon_max, lat_max, width, height)
        
        # Write data GeoTIFF (raw values)
        data_file = output_dir / f"tbofs_sst_{valid_timestamp}_{forecast_part}.tif"
        
        profile = {
            'driver': 'GTiff',
            'dtype': 'float32',
            'width': width,
            'height': height,
            'count': 1,
            'crs': CRS.from_epsg(4326),
            'transform': transform,
            'compress': 'deflate',
            'tiled': True,
            'blockxsize': 256,
            'blockysize': 256,
            'nodata': np.nan
        }
        
        with rasterio.open(data_file, 'w', **profile) as dst:
            dst.write(temp_values, 1)
            dst.set_band_description(1, 'sea_surface_temperature')
            dst.update_tags(
                VALID_TIME=str(valid_timestamp),
                UNITS='degC',
                LONG_NAME='Sea Surface Temperature'
            )
        
        logger.info(f"✓ Created data file: {data_file.name}")
        
        # Create colored version for visualization
        colored_file = None
        if colorize and MATPLOTLIB_AVAILABLE:
            colored_file = output_dir / f"tbofs_sst_{valid_timestamp}_{forecast_part}_colored.tif"
            
            cmap, min_temp, max_temp = create_colormap()
            
            # Normalize temperature to 0-1 range
            temp_normalized = (temp_values - min_temp) / (max_temp - min_temp)
            temp_normalized = np.clip(temp_normalized, 0, 1)
            
            # Apply colormap
            rgba = cmap(temp_normalized)
            
            # Convert to uint8
            rgba_uint8 = (rgba * 255).astype(np.uint8)
            
            # Set transparent where NaN
            mask = np.isnan(temp_values)
            rgba_uint8[mask] = [0, 0, 0, 0]
            
            # Write colored GeoTIFF (4 bands: RGBA)
            colored_profile = profile.copy()
            colored_profile.update({
                'dtype': 'uint8',
                'count': 4,
                'nodata': None
            })
            
            with rasterio.open(colored_file, 'w', **colored_profile) as dst:
                for i in range(4):
                    dst.write(rgba_uint8[:, :, i], i + 1)
                dst.update_tags(
                    VALID_TIME=str(valid_timestamp),
                    COLOR_RANGE=f"{min_temp}-{max_temp}",
                    UNITS='degC'
                )
            
            logger.info(f"✓ Created colored file: {colored_file.name}")
        
        return (data_file, colored_file)
        
    except Exception as e:
        logger.error(f"Failed to process {nc_file.name}: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Process TBOFS sea surface temperature'
    )
    
    parser.add_argument('--input-dir', '-i', type=Path, required=True,
                        help='Input directory with TBOFS NetCDF files')
    parser.add_argument('--output-dir', '-o', type=Path, required=True,
                        help='Output directory for processed files')
    parser.add_argument('--colorize', action='store_true',
                        help='Create colored visualization files')
    parser.add_argument('--hours', type=str, default=None,
                        help='Filter to specific forecast hours')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose logging')
    
    args = parser.parse_args()
    logger = setup_logging(args.verbose)
    
    if not XARRAY_AVAILABLE or not RASTERIO_AVAILABLE:
        logger.error("Required packages missing. Install with:")
        logger.error("  pip install xarray netCDF4 rasterio matplotlib")
        return 1
    
    logger.info("=" * 60)
    logger.info("TBOFS Temperature Processing")
    logger.info("=" * 60)
    
    # Find NetCDF files
    nc_files = sorted(args.input_dir.glob("*.fields.*.nc"))
    
    if not nc_files:
        logger.error(f"No NetCDF files found in {args.input_dir}")
        return 1
    
    # Filter by hours if specified
    if args.hours:
        hours = set()
        for part in args.hours.split(','):
            if '-' in part:
                start, end = map(int, part.split('-'))
                hours.update(range(start, end + 1))
            else:
                hours.add(int(part))
        
        filtered = []
        for f in nc_files:
            if '.fields.f' in f.name:
                hour = int(f.name.split('.fields.f')[1].split('.')[0])
                if hour in hours:
                    filtered.append(f)
            elif '.fields.n' in f.name:
                filtered.append(f)
        nc_files = filtered
    
    logger.info(f"Found {len(nc_files)} NetCDF files to process")
    
    processed = []
    
    for nc_file in nc_files:
        result = extract_sst(nc_file, args.output_dir, args.colorize, logger)
        if result:
            processed.append(result)
    
    # Summary
    logger.info(f"\n{'=' * 60}")
    logger.info("Processing Summary")
    logger.info(f"{'=' * 60}")
    logger.info(f"Files processed: {len(processed)}")
    logger.info(f"Output directory: {args.output_dir}")
    
    return 0 if processed else 1


if __name__ == '__main__':
    sys.exit(main())
