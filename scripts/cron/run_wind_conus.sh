#!/bin/bash
# Run wind resampling for CONUS at 1x resolution (national overview layer)

set -e

echo "=== $(date) - Starting CONUS wind tileset update (1x) ==="

cd /home/ubuntu/clawd/WeatherData-hires/scripts/hrrr

# Activate conda environment
source ~/anaconda3/etc/profile.d/conda.sh
conda activate wind-resampling

# Run for CONUS
python upload_wind_resampled.py --latest --region conus --scale 1 --fxx 0

echo "=== $(date) - CONUS wind tileset update complete ==="
