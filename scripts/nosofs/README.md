# NOSOFS Scripts (NOS Operational Forecast Systems)

Scripts for downloading and processing NOAA ocean forecast data for coastal regions.

## TBOFS (Tampa Bay Operational Forecast System)

High-resolution (~100m) coastal ocean model for Tampa Bay, Florida.

### Available Data
- **Sea Surface Temperature** (°C)
- **Ocean Currents** (u/v components, m/s)
- **Water Level** (m)
- **Salinity** (PSU)

### Data Source
```
https://nomads.ncep.noaa.gov/pub/data/nccf/com/nosofs/prod/tbofs.{YYYYMMDD}/
```

### Scripts

#### 1. Download TBOFS Data
```bash
# Download latest forecast (48 hours)
python download_tbofs.py --latest

# Download specific date/cycle
python download_tbofs.py --date 2026-02-04 --cycle 00

# Download only first 6 forecast hours
python download_tbofs.py --latest --hours 1-6

# Include nowcast (analysis) files
python download_tbofs.py --latest --nowcast
```

#### 2. Process Ocean Currents (for Mapbox raster-particle)
```bash
# Process currents to GeoTIFF
python process_tbofs_currents.py \
    --input-dir /tmp/tbofs-data \
    --output-dir /tmp/tbofs-currents

# Process only specific hours
python process_tbofs_currents.py \
    --input-dir /tmp/tbofs-data \
    --output-dir /tmp/tbofs-currents \
    --hours 1-6
```

#### 3. Upload Currents to Mapbox
```bash
# Upload to Mapbox (requires MAPBOX_ACCESS_TOKEN)
export MAPBOX_ACCESS_TOKEN="your_token"

python upload_tbofs_currents.py \
    --input-dir /tmp/tbofs-currents/geotiff

# Custom tileset name
python upload_tbofs_currents.py \
    --input-dir /tmp/tbofs-currents/geotiff \
    --tileset tbofs_currents_tampa
```

#### 4. Process Temperature (for S3 tiles)
```bash
# Process SST to GeoTIFF
python process_tbofs_temperature.py \
    --input-dir /tmp/tbofs-data \
    --output-dir /tmp/tbofs-temp

# With colored visualization
python process_tbofs_temperature.py \
    --input-dir /tmp/tbofs-data \
    --output-dir /tmp/tbofs-temp \
    --colorize
```

### Full Pipeline Example
```bash
# 1. Download latest data
python download_tbofs.py --latest --hours 1-6 -o /tmp/tbofs

# 2. Process currents
python process_tbofs_currents.py -i /tmp/tbofs -o /tmp/tbofs-processed

# 3. Upload currents to Mapbox
python upload_tbofs_currents.py -i /tmp/tbofs-processed/geotiff

# 4. Process temperature for S3
python process_tbofs_temperature.py -i /tmp/tbofs -o /tmp/tbofs-temp --colorize
```

### Mapbox Layer Usage

Once uploaded, use the tileset in a raster-particle layer:

```javascript
// Source
{
  type: "raster-array",
  url: "mapbox://onwaterllc.tbofs_currents",
  tileSize: 512
}

// Layer
{
  id: "ocean-currents",
  type: "raster-particle",
  source: "tbofs-currents",
  paint: {
    "raster-particle-array-band": bandValue,
    "raster-particle-speed-factor": 0.2,  // Slower than wind
    "raster-particle-count": 8000,
    "raster-particle-max-speed": 3,  // Ocean currents are slower
    "raster-particle-color": [
      "interpolate", ["linear"], ["raster-particle-speed"],
      0.0, "rgba(100,100,255,255)",  // Blue - slow
      0.5, "rgba(100,255,100,255)",  // Green
      1.0, "rgba(255,255,100,255)",  // Yellow
      2.0, "rgba(255,100,100,255)"   // Red - fast
    ]
  }
}
```

### Other NOSOFS Models

Similar scripts can be adapted for other coastal models:

| Model | Region | Resolution |
|-------|--------|------------|
| gomofs | Gulf of Maine | ~700m |
| cbofs | Chesapeake Bay | ~100m |
| dbofs | Delaware Bay | ~100m |
| sfbofs | San Francisco Bay | ~100m |
| ngofs2 | Northern Gulf of Mexico | ~500m |
| wcofs | West Coast | ~4km |

### Requirements
```bash
pip install requests xarray netCDF4 numpy rasterio matplotlib
```
