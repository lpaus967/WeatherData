#!/usr/bin/env python3
"""
Clip resampled wind GeoTIFF to Vermont bounds.

Usage:
    python clip_to_vermont.py input.tif output.tif
    python clip_to_vermont.py input.tif  # outputs to input_vermont.tif
"""

import argparse
import sys
from pathlib import Path

import rasterio
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.crs import CRS
import numpy as np

# Vermont bounding box (WGS84)
VERMONT_BOUNDS = {
    'west': -73.44,
    'east': -71.47,
    'south': 42.73,
    'north': 45.02
}

# Add a small buffer for clean edges
BUFFER = 0.1  # degrees


def create_bbox_geojson(bounds: dict, buffer: float = 0) -> dict:
    """Create a GeoJSON polygon from bounds."""
    west = bounds['west'] - buffer
    east = bounds['east'] + buffer
    south = bounds['south'] - buffer
    north = bounds['north'] + buffer
    
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south]
        ]]
    }


def clip_to_vermont(input_path: Path, output_path: Path, buffer: float = BUFFER) -> bool:
    """
    Clip a GeoTIFF to Vermont bounds.
    
    Handles reprojection if the input is not in WGS84.
    """
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    
    with rasterio.open(input_path) as src:
        print(f"Source CRS: {src.crs}")
        print(f"Source shape: {src.width}x{src.height}, {src.count} bands")
        print(f"Source bounds: {src.bounds}")
        
        # Target CRS (Web Mercator for Mapbox, or WGS84)
        dst_crs = CRS.from_epsg(4326)  # WGS84
        
        # If source is not WGS84, we need to reproject first
        if src.crs != dst_crs:
            print(f"Reprojecting from {src.crs} to {dst_crs}...")
            
            # Calculate transform for reprojection
            transform, width, height = calculate_default_transform(
                src.crs, dst_crs, src.width, src.height, *src.bounds
            )
            
            # Reproject to memory
            reprojected_data = np.zeros((src.count, height, width), dtype=src.dtypes[0])
            
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=reprojected_data[i-1],
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear
                )
            
            # Create profile for reprojected data
            profile = src.profile.copy()
            profile.update({
                'crs': dst_crs,
                'transform': transform,
                'width': width,
                'height': height
            })
            
            # Now clip the reprojected data
            bbox = create_bbox_geojson(VERMONT_BOUNDS, buffer)
            
            # Calculate pixel coordinates for the bbox
            from rasterio.windows import from_bounds
            window = from_bounds(
                VERMONT_BOUNDS['west'] - buffer,
                VERMONT_BOUNDS['south'] - buffer,
                VERMONT_BOUNDS['east'] + buffer,
                VERMONT_BOUNDS['north'] + buffer,
                transform
            )
            
            # Round window to integers
            row_start = max(0, int(window.row_off))
            row_stop = min(height, int(window.row_off + window.height))
            col_start = max(0, int(window.col_off))
            col_stop = min(width, int(window.col_off + window.width))
            
            # Clip the data
            clipped_data = reprojected_data[:, row_start:row_stop, col_start:col_stop]
            
            # Update transform for clipped area
            from rasterio.transform import from_bounds as transform_from_bounds
            clipped_transform = transform_from_bounds(
                VERMONT_BOUNDS['west'] - buffer,
                VERMONT_BOUNDS['south'] - buffer,
                VERMONT_BOUNDS['east'] + buffer,
                VERMONT_BOUNDS['north'] + buffer,
                clipped_data.shape[2],
                clipped_data.shape[1]
            )
            
            # Write output
            profile.update({
                'width': clipped_data.shape[2],
                'height': clipped_data.shape[1],
                'transform': clipped_transform
            })
            
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(clipped_data)
                dst.set_band_description(1, 'u10')
                dst.set_band_description(2, 'v10')
            
            print(f"Output shape: {clipped_data.shape[2]}x{clipped_data.shape[1]}")
            print(f"Output bounds: {VERMONT_BOUNDS}")
            
        else:
            # Source is already WGS84, just clip
            bbox = create_bbox_geojson(VERMONT_BOUNDS, buffer)
            
            clipped_data, clipped_transform = mask(
                src, [bbox], crop=True, all_touched=True
            )
            
            profile = src.profile.copy()
            profile.update({
                'width': clipped_data.shape[2],
                'height': clipped_data.shape[1],
                'transform': clipped_transform
            })
            
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(clipped_data)
                dst.set_band_description(1, 'u10')
                dst.set_band_description(2, 'v10')
            
            print(f"Output shape: {clipped_data.shape[2]}x{clipped_data.shape[1]}")
    
    print(f"✓ Clipped to Vermont: {output_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description='Clip wind GeoTIFF to Vermont')
    parser.add_argument('input', type=Path, help='Input GeoTIFF')
    parser.add_argument('output', type=Path, nargs='?', help='Output GeoTIFF (optional)')
    parser.add_argument('--buffer', type=float, default=BUFFER, help=f'Buffer in degrees (default: {BUFFER})')
    
    args = parser.parse_args()
    
    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}")
        return 1
    
    if args.output is None:
        args.output = args.input.with_stem(args.input.stem + '_vermont')
    
    try:
        clip_to_vermont(args.input, args.output, args.buffer)
        return 0
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
