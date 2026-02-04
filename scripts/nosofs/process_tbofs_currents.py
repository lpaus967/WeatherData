#!/usr/bin/env python3
"""
TBOFS Current Processing Script

Converts TBOFS NetCDF ocean current data (u/v) to GRIB format
suitable for Mapbox raster-particle layer visualization.

The output GRIB files contain:
- Band 1: u-component (eastward current, m/s)
- Band 2: v-component (northward current, m/s)

Requirements:
    pip install xarray netCDF4 numpy rasterio

Usage:
    python process_tbofs_currents.py --input-dir /tmp/tbofs-data --output-dir /tmp/tbofs-currents
"""

import argparse
import logging
import sys
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import numpy as np

# Try importing optional dependencies
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


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger('tbofs_currents')


def extract_surface_currents(
    nc_file: Path,
    output_dir: Path,
    logger: logging.Logger
) -> Optional[Path]:
    """
    Extract surface currents from TBOFS NetCDF and save as GeoTIFF.
    
    TBOFS uses ROMS format with:
    - u: eastward velocity on u-grid
    - v: northward velocity on v-grid
    - We need surface layer (s_rho = -1 or top layer)
    
    Args:
        nc_file: Input NetCDF file
        output_dir: Output directory
        logger: Logger instance
    
    Returns:
        Path to output GeoTIFF or None if failed
    """
    # Fix PROJ database conflicts (Anaconda vs system)
    os.environ.pop('PROJ_LIB', None)
    os.environ.pop('PROJ_DATA', None)
    
    if not XARRAY_AVAILABLE:
        logger.error("xarray is required. Install with: pip install xarray netCDF4")
        return None
    
    try:
        ds = xr.open_dataset(nc_file)
        
        # Find time and valid_time
        if 'ocean_time' in ds:
            time_var = ds['ocean_time']
            if hasattr(time_var, 'values') and len(time_var.values) > 0:
                valid_time = time_var.values[0]
                if hasattr(valid_time, 'astype'):
                    # Convert numpy datetime64 to timestamp
                    valid_timestamp = int(valid_time.astype('datetime64[s]').astype('int64'))
                else:
                    valid_timestamp = int(datetime.utcnow().timestamp())
            else:
                valid_timestamp = int(datetime.utcnow().timestamp())
        else:
            valid_timestamp = int(datetime.utcnow().timestamp())
        
        logger.info(f"Processing: {nc_file.name}")
        logger.info(f"Valid time: {datetime.utcfromtimestamp(valid_timestamp)}")
        
        # Get u and v currents (surface layer)
        # TBOFS variables: u_eastward, v_northward (already on rho grid)
        # or u_sur, v_sur for surface
        
        u_var = None
        v_var = None
        
        # Try different variable names
        u_names = ['u_eastward', 'u_sur', 'u', 'water_u']
        v_names = ['v_northward', 'v_sur', 'v', 'water_v']
        
        for name in u_names:
            if name in ds:
                u_var = name
                break
        
        for name in v_names:
            if name in ds:
                v_var = name
                break
        
        if u_var is None or v_var is None:
            logger.error(f"Could not find u/v variables. Available: {list(ds.data_vars)}")
            ds.close()
            return None
        
        logger.info(f"Using variables: {u_var}, {v_var}")
        
        # Extract data
        u_data = ds[u_var]
        v_data = ds[v_var]
        
        # Get surface layer (last index in s_rho dimension, or squeeze if 2D)
        if 's_rho' in u_data.dims:
            u_surface = u_data.isel(s_rho=-1)  # Surface is last index
            v_surface = v_data.isel(s_rho=-1)
        elif 'Nz' in u_data.dims:
            u_surface = u_data.isel(Nz=-1)
            v_surface = v_data.isel(Nz=-1)
        else:
            u_surface = u_data
            v_surface = v_data
        
        # Squeeze time dimension if present
        if 'ocean_time' in u_surface.dims:
            u_surface = u_surface.isel(ocean_time=0)
            v_surface = v_surface.isel(ocean_time=0)
        
        # Get coordinates (use rho grid coordinates)
        if 'lon_rho' in ds:
            lon = ds['lon_rho'].values
            lat = ds['lat_rho'].values
        elif 'lon_psi' in ds:
            lon = ds['lon_psi'].values
            lat = ds['lat_psi'].values
        elif 'Longitude' in ds:
            lon = ds['Longitude'].values
            lat = ds['Latitude'].values
        else:
            # Try to find any lon/lat variables
            lon_vars = [v for v in ds.coords if 'lon' in v.lower()]
            lat_vars = [v for v in ds.coords if 'lat' in v.lower()]
            if lon_vars and lat_vars:
                lon = ds[lon_vars[0]].values
                lat = ds[lat_vars[0]].values
            else:
                logger.error(f"Could not find coordinate variables. Available: {list(ds.coords)}")
                ds.close()
                return None
        
        # Get data as numpy arrays
        u_values = u_surface.values.astype(np.float32)
        v_values = v_surface.values.astype(np.float32)
        
        # Handle masked/fill values
        if hasattr(u_values, 'filled'):
            u_values = u_values.filled(np.nan)
            v_values = v_values.filled(np.nan)
        
        # Replace fill values with NaN
        fill_value = -9999.0
        u_values = np.where(np.abs(u_values) > 100, np.nan, u_values)
        v_values = np.where(np.abs(v_values) > 100, np.nan, v_values)
        
        logger.info(f"U grid shape: {u_values.shape}")
        logger.info(f"V grid shape: {v_values.shape}")
        
        # ROMS uses staggered Arakawa C-grid: u and v are on different grids
        # Interpolate to common rho grid by averaging adjacent cells
        if u_values.shape != v_values.shape:
            logger.info("Interpolating staggered grids to common rho grid...")
            
            # u is on xi_u grid (one less in xi direction)
            # v is on eta_v grid (one less in eta direction)
            # Interpolate to rho grid
            
            if u_values.shape[1] < v_values.shape[1]:
                # u has fewer columns - interpolate in xi direction
                u_interp = (u_values[:, :-1] + u_values[:, 1:]) / 2 if u_values.shape[1] > 1 else u_values
                # Pad to match v shape if needed
                if u_interp.shape[1] < v_values.shape[1]:
                    u_interp = np.pad(u_interp, ((0, 0), (0, v_values.shape[1] - u_interp.shape[1])), 
                                      mode='edge')
                u_values = u_interp[:v_values.shape[0], :v_values.shape[1]]
            
            if v_values.shape[0] < u_values.shape[0]:
                # v has fewer rows - interpolate in eta direction
                v_interp = (v_values[:-1, :] + v_values[1:, :]) / 2 if v_values.shape[0] > 1 else v_values
                # Pad to match u shape if needed
                if v_interp.shape[0] < u_values.shape[0]:
                    v_interp = np.pad(v_interp, ((0, u_values.shape[0] - v_interp.shape[0]), (0, 0)), 
                                      mode='edge')
                v_values = v_interp[:u_values.shape[0], :u_values.shape[1]]
            
            # Final shape matching - take the minimum common shape
            min_rows = min(u_values.shape[0], v_values.shape[0])
            min_cols = min(u_values.shape[1], v_values.shape[1])
            u_values = u_values[:min_rows, :min_cols]
            v_values = v_values[:min_rows, :min_cols]
            
            logger.info(f"Interpolated to common shape: {u_values.shape}")
        
        logger.info(f"Grid shape: {u_values.shape}")
        logger.info(f"U range: {np.nanmin(u_values):.3f} to {np.nanmax(u_values):.3f} m/s")
        logger.info(f"V range: {np.nanmin(v_values):.3f} to {np.nanmax(v_values):.3f} m/s")
        
        ds.close()
        
        # Calculate bounds from coordinate arrays
        # Trim coordinates to match data shape if needed
        if lon.ndim == 2:
            if lon.shape != u_values.shape:
                # Trim to match data grid
                lon = lon[:u_values.shape[0], :u_values.shape[1]]
                lat = lat[:u_values.shape[0], :u_values.shape[1]]
            lon_min, lon_max = float(np.nanmin(lon)), float(np.nanmax(lon))
            lat_min, lat_max = float(np.nanmin(lat)), float(np.nanmax(lat))
        else:
            lon_min, lon_max = float(lon.min()), float(lon.max())
            lat_min, lat_max = float(lat.min()), float(lat.max())
        
        logger.info(f"Bounds: [{lon_min:.4f}, {lat_min:.4f}, {lon_max:.4f}, {lat_max:.4f}]")
        
        # Create output GeoTIFF
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract forecast hour from filename (e.g., f001, n001)
        stem = nc_file.stem
        if '.fields.' in stem:
            forecast_part = stem.split('.fields.')[-1]  # e.g., "f001"
        else:
            forecast_part = "f000"
        
        output_file = output_dir / f"tbofs_currents_{valid_timestamp}_{forecast_part}.tif"
        
        height, width = u_values.shape
        
        transform = from_bounds(lon_min, lat_min, lon_max, lat_max, width, height)
        
        # Stack u and v into 2 bands
        data = np.stack([u_values, v_values], axis=0)
        
        # Write GeoTIFF
        profile = {
            'driver': 'GTiff',
            'dtype': 'float32',
            'width': width,
            'height': height,
            'count': 2,
            'crs': CRS.from_epsg(4326),
            'transform': transform,
            'compress': 'deflate',
            'tiled': True,
            'blockxsize': 256,
            'blockysize': 256,
            'nodata': np.nan
        }
        
        with rasterio.open(output_file, 'w', **profile) as dst:
            dst.write(data)
            dst.set_band_description(1, 'u_current')
            dst.set_band_description(2, 'v_current')
            dst.update_tags(VALID_TIME=str(valid_timestamp))
        
        logger.info(f"✓ Created: {output_file.name}")
        return output_file
        
    except Exception as e:
        logger.error(f"Failed to process {nc_file.name}: {e}")
        import traceback
        traceback.print_exc()
        return None


def convert_to_grib(
    geotiff_file: Path,
    output_dir: Path,
    logger: logging.Logger
) -> Optional[Path]:
    """
    Convert GeoTIFF to GRIB format for Mapbox raster-particle layer.
    
    Adds required GRIB metadata for the recipe filters.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get valid time from filename
    parts = geotiff_file.stem.split('_')
    valid_timestamp = parts[2] if len(parts) > 2 else str(int(datetime.utcnow().timestamp()))
    forecast_part = parts[3] if len(parts) > 3 else "f000"
    
    output_file = output_dir / f"tbofs_currents_{valid_timestamp}_{forecast_part}.grib2"
    
    # Fix PROJ database conflicts
    env = os.environ.copy()
    env.pop('PROJ_LIB', None)
    env.pop('PROJ_DATA', None)
    
    try:
        # Convert to GRIB using gdal_translate
        # Note: GRIB output requires specific metadata
        cmd = [
            'gdal_translate',
            '-of', 'GRIB',
            '-co', f'GRIB_COMMENT=ocean current [m/s]',
            str(geotiff_file),
            str(output_file)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
        
        if result.returncode != 0:
            logger.warning(f"GRIB conversion warning: {result.stderr}")
            # GRIB conversion often has warnings but still works
        
        if output_file.exists():
            logger.info(f"✓ Converted to GRIB: {output_file.name}")
            return output_file
        else:
            logger.error("GRIB file was not created")
            return None
            
    except Exception as e:
        logger.error(f"GRIB conversion failed: {e}")
        return None


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Process TBOFS currents for Mapbox raster-particle layer'
    )
    
    parser.add_argument('--input-dir', '-i', type=Path, required=True,
                        help='Input directory with TBOFS NetCDF files')
    parser.add_argument('--output-dir', '-o', type=Path, required=True,
                        help='Output directory for processed files')
    parser.add_argument('--format', choices=['tif', 'grib', 'both'], default='tif',
                        help='Output format (default: tif)')
    parser.add_argument('--hours', type=str, default=None,
                        help='Filter to specific forecast hours (e.g., "1-6")')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose logging')
    
    args = parser.parse_args()
    logger = setup_logging(args.verbose)
    
    if not XARRAY_AVAILABLE or not RASTERIO_AVAILABLE:
        logger.error("Required packages missing. Install with:")
        logger.error("  pip install xarray netCDF4 rasterio")
        return 1
    
    logger.info("=" * 60)
    logger.info("TBOFS Current Processing")
    logger.info("=" * 60)
    
    # Find NetCDF files
    nc_files = sorted(args.input_dir.glob("*.fields.*.nc"))
    
    if not nc_files:
        logger.error(f"No NetCDF files found in {args.input_dir}")
        return 1
    
    # Filter by forecast hours if specified
    if args.hours:
        hours = set()
        for part in args.hours.split(','):
            if '-' in part:
                start, end = map(int, part.split('-'))
                hours.update(range(start, end + 1))
            else:
                hours.add(int(part))
        
        filtered_files = []
        for f in nc_files:
            # Extract hour from filename (e.g., f001, n001)
            if '.fields.f' in f.name:
                hour = int(f.name.split('.fields.f')[1].split('.')[0])
                if hour in hours:
                    filtered_files.append(f)
            elif '.fields.n' in f.name:
                # Include nowcast files
                filtered_files.append(f)
        
        nc_files = filtered_files
    
    logger.info(f"Found {len(nc_files)} NetCDF files to process")
    
    # Create output directories
    tif_dir = args.output_dir / "geotiff"
    grib_dir = args.output_dir / "grib"
    
    processed_tifs = []
    processed_gribs = []
    
    for nc_file in nc_files:
        # Extract to GeoTIFF
        tif_file = extract_surface_currents(nc_file, tif_dir, logger)
        
        if tif_file:
            processed_tifs.append(tif_file)
            
            # Convert to GRIB if requested
            if args.format in ['grib', 'both']:
                grib_file = convert_to_grib(tif_file, grib_dir, logger)
                if grib_file:
                    processed_gribs.append(grib_file)
    
    # Summary
    logger.info(f"\n{'=' * 60}")
    logger.info("Processing Summary")
    logger.info(f"{'=' * 60}")
    logger.info(f"GeoTIFFs created: {len(processed_tifs)}")
    if args.format in ['grib', 'both']:
        logger.info(f"GRIB files created: {len(processed_gribs)}")
    logger.info(f"Output directory: {args.output_dir}")
    
    return 0 if processed_tifs else 1


if __name__ == '__main__':
    sys.exit(main())
