#!/bin/bash
# Run wind resampling for all 5 regional tilesets at 6x resolution
# Regions: northeast, southeast, northwest, southwest, west_coast

set -e

echo "=== $(date) - Starting regional wind tileset updates (6x) ==="

cd /home/ubuntu/clawd/WeatherData-hires/scripts/hrrr

# Activate conda environment
source ~/anaconda3/etc/profile.d/conda.sh
conda activate wind-resampling

# Run for all regions
python upload_wind_resampled.py --latest --region all --scale 6 --fxx 0

echo "=== $(date) - Regional wind tileset updates complete ==="
