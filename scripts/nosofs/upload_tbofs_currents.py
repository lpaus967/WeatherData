#!/usr/bin/env python3
"""
TBOFS Ocean Currents Mapbox Upload Script

Uploads processed TBOFS current data to Mapbox as a rasterarray tileset
suitable for raster-particle layer visualization (similar to wind particles).

Tileset: onwaterllc.tbofs_currents

Requirements:
    pip install requests

Usage:
    python upload_tbofs_currents.py --input-dir /tmp/tbofs-currents/geotiff
    python upload_tbofs_currents.py --input-dir /tmp/tbofs-currents/geotiff --tileset tbofs_currents_test
"""

import argparse
import logging
import sys
import os
import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import requests

# Configuration
MAPBOX_USERNAME = "onwaterllc"
DEFAULT_TILESET_NAME = "tbofs_currents"
MAPBOX_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "")


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger('tbofs_upload')


class MapboxUploader:
    """Handle Mapbox MTS rasterarray tileset uploads for ocean currents."""
    
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
    
    async def upload_files_to_source(self, files: List[Path], replace: bool = True) -> bool:
        """Upload GeoTIFF files to tileset source using multipart upload."""
        if not files:
            self.logger.error("No files to upload")
            return False
        
        self.logger.info(f"Uploading {len(files)} file(s) to source...")
        
        if replace:
            if not await self.delete_tileset_source():
                return False
            await asyncio.sleep(5)
        
        url = f"https://api.mapbox.com/tilesets/v1/sources/{self.username}/{self.tileset_name}?access_token={self.token}"
        
        try:
            file_handles = []
            files_data = []
            
            for f in files:
                fh = open(f, 'rb')
                file_handles.append(fh)
                files_data.append(('file', (f.name, fh, 'application/octet-stream')))
            
            self.logger.info(f"Uploading to Mapbox...")
            response = requests.post(url, files=files_data, timeout=600)
            
            # Close file handles
            for fh in file_handles:
                fh.close()
            
            if response.ok:
                self.logger.info(f"✓ Uploaded {len(files)} file(s)")
                return True
            else:
                self.logger.error(f"Upload failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"Upload error: {e}")
            return False
    
    def create_recipe(self, output_path: Path) -> Path:
        """Create Mapbox rasterarray recipe for ocean currents."""
        recipe = {
            "version": 1,
            "type": "rasterarray",
            "sources": [
                {"uri": f"mapbox://tileset-source/{self.username}/{self.tileset_name}"}
            ],
            "layers": {
                "currents": {
                    "tilesize": 512,
                    "resampling": "bilinear",
                    "minzoom": 0,
                    "maxzoom": 14,  # High zoom for coastal detail
                    "source_rules": {
                        # Use VALID_TIME tag from GeoTIFF for band naming
                        "name": ["get", "VALID_TIME"],
                        "sort_key": ["to-number", ["get", "VALID_TIME"]],
                        "order": "asc"
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
            json={
                "recipe": recipe,
                "name": f"TBOFS Ocean Currents",
                "description": "Tampa Bay ocean currents for raster-particle visualization"
            }
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
    files: List[Path],
    tileset_name: str,
    logger: logging.Logger
) -> bool:
    """Upload processed current files to Mapbox."""
    if not MAPBOX_TOKEN:
        logger.error("MAPBOX_ACCESS_TOKEN not set")
        return False
    
    uploader = MapboxUploader(MAPBOX_USERNAME, tileset_name, MAPBOX_TOKEN, logger)
    
    # Create recipe
    recipe_path = files[0].parent.parent / "recipe.json"
    uploader.create_recipe(recipe_path)
    
    # Upload files
    if not await uploader.upload_files_to_source(files, replace=True):
        return False
    
    await asyncio.sleep(10)
    
    # Create/update tileset
    if not await uploader.create_or_update_tileset(recipe_path):
        return False
    
    await asyncio.sleep(5)
    
    # Publish
    if not await uploader.publish():
        return False
    
    await asyncio.sleep(10)
    await uploader.check_status()
    
    logger.info(f"\n✓ Tileset available at: mapbox://{MAPBOX_USERNAME}.{tileset_name}")
    logger.info(f"View in Studio: https://studio.mapbox.com/tilesets/{MAPBOX_USERNAME}.{tileset_name}/")
    return True


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Upload TBOFS ocean currents to Mapbox'
    )
    
    parser.add_argument('--input-dir', '-i', type=Path, required=True,
                        help='Directory with processed GeoTIFF files')
    parser.add_argument('--tileset', type=str, default=DEFAULT_TILESET_NAME,
                        help=f'Mapbox tileset name (default: {DEFAULT_TILESET_NAME})')
    parser.add_argument('--hours', type=str, default=None,
                        help='Filter to specific forecast hours')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose logging')
    
    args = parser.parse_args()
    logger = setup_logging(args.verbose)
    
    logger.info("=" * 60)
    logger.info("TBOFS Currents Mapbox Upload")
    logger.info("=" * 60)
    
    # Find GeoTIFF files
    tif_files = sorted(args.input_dir.glob("*.tif"))
    
    if not tif_files:
        logger.error(f"No GeoTIFF files found in {args.input_dir}")
        return 1
    
    logger.info(f"Found {len(tif_files)} files to upload")
    logger.info(f"Tileset: {MAPBOX_USERNAME}.{args.tileset}")
    
    # Upload
    success = asyncio.run(upload_to_mapbox(tif_files, args.tileset, logger))
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
