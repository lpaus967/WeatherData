# Data Processing Scripts

Scripts for processing weather data (NetCDF/GRIB2 to Cloud Optimized GeoTIFF).

## Purpose

Process downloaded weather data into web-friendly formats:
- Convert NetCDF to Cloud Optimized GeoTIFF (COG)
- Reproject to Web Mercator (EPSG:3857)
- Apply unit conversions (Kelvin to Celsius, etc.)
- Apply color ramps for visualization

## Planned Scripts

- `process_weather.py` - Main processing script (TICKET-006)
- `apply_colormap.py` - Color ramp application (TICKET-007)
- `generate_tiles.py` - Tile generation (TICKET-008)

Status: Coming after TICKET-004 (download) is complete.
