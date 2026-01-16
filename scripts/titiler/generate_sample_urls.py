#!/usr/bin/env python3
"""
Generate Sample TiTiler URLs

Generates sample URLs for testing TiTiler against existing COGs in S3.

Usage:
    python generate_sample_urls.py
    python generate_sample_urls.py --format curl
    python generate_sample_urls.py --variable temperature_2m --hours 6
"""

import argparse
from datetime import datetime, timedelta
from urllib.parse import quote


# Configuration
S3_BUCKET = "sat-data-automation-test"
S3_PREFIX = "processed-cogs"
TITILER_BASE_URL = "http://localhost:8000"

# Available weather variables (matching actual file naming)
VARIABLES = [
    "temperature_2m",
    "dewpoint_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_gust_10m",
    "wind_direction_10m",
    "total_cloud_cover",
    "low_cloud_cover",
    "visibility",
    "precipitation_rate",
    "snow_depth",
    "freezing_level",
]

# Sample tiles covering CONUS at different zoom levels
SAMPLE_TILES = [
    (2, 0, 1),    # Very low zoom
    (3, 1, 3),    # Low zoom
    (4, 3, 6),    # Medium zoom
    (5, 7, 12),   # Higher zoom
]


def get_recent_timestamps(hours_back: int = 48, interval: int = 6) -> list[dict]:
    """Generate recent forecast timestamps with full date info."""
    timestamps = []
    current = datetime.utcnow()

    # Round to nearest 6-hour interval
    hour = (current.hour // interval) * interval
    start = current.replace(hour=hour, minute=0, second=0, microsecond=0)

    # Go back in time
    for i in range(hours_back // interval):
        ts = start - timedelta(hours=i * interval)
        timestamps.append({
            "year": ts.strftime("%Y"),
            "month": ts.strftime("%m"),
            "day": ts.strftime("%d"),
            "hour": ts.hour,
            "date_compact": ts.strftime("%Y%m%d"),
            "display": ts.strftime("%Y-%m-%dT%HZ"),
        })

    return timestamps


def generate_cog_url(
    variable: str,
    timestamp: dict,
    forecast_hour: int = 0,
) -> str:
    """Generate S3 URL for a COG file."""
    filename = f"{variable}_hrrr.{timestamp['date_compact']}.t{timestamp['hour']:02d}z.f{forecast_hour:02d}.tif"
    return f"s3://{S3_BUCKET}/{S3_PREFIX}/{timestamp['year']}/{timestamp['month']}/{timestamp['day']}/{filename}"


def generate_tile_url(
    cog_url: str,
    z: int,
    x: int,
    y: int,
    titiler_url: str = TITILER_BASE_URL,
) -> str:
    """Generate TiTiler tile URL with WebMercatorQuad."""
    return f"{titiler_url}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png?url={quote(cog_url, safe='')}"


def generate_info_url(cog_url: str, titiler_url: str = TITILER_BASE_URL) -> str:
    """Generate TiTiler info URL."""
    return f"{titiler_url}/cog/info?url={quote(cog_url, safe='')}"


def generate_tilejson_url(cog_url: str, titiler_url: str = TITILER_BASE_URL) -> str:
    """Generate TiTiler TileJSON URL."""
    return f"{titiler_url}/cog/WebMercatorQuad/tilejson.json?url={quote(cog_url, safe='')}"


def generate_statistics_url(cog_url: str, titiler_url: str = TITILER_BASE_URL) -> str:
    """Generate TiTiler statistics URL."""
    return f"{titiler_url}/cog/statistics?url={quote(cog_url, safe='')}"


def generate_preview_url(
    cog_url: str,
    max_size: int = 512,
    titiler_url: str = TITILER_BASE_URL,
) -> str:
    """Generate TiTiler preview URL."""
    return f"{titiler_url}/cog/preview?url={quote(cog_url, safe='')}&max_size={max_size}"


def generate_point_url(
    cog_url: str,
    lon: float,
    lat: float,
    titiler_url: str = TITILER_BASE_URL,
) -> str:
    """Generate TiTiler point query URL."""
    # TiTiler uses comma separator for coordinates
    return f"{titiler_url}/cog/point/{lon},{lat}?url={quote(cog_url, safe='')}"


def print_urls(urls: list[str], format_type: str = "plain"):
    """Print URLs in specified format."""
    for url in urls:
        if format_type == "curl":
            print(f'curl "{url}"')
        elif format_type == "curl-output":
            # Extract a filename from the URL
            filename = url.split("/")[-1].split("?")[0]
            print(f'curl "{url}" --output {filename}')
        else:
            print(url)


def main():
    parser = argparse.ArgumentParser(description="Generate TiTiler test URLs")
    parser.add_argument(
        "--variable",
        default="temperature_2m",
        choices=VARIABLES,
        help="Weather variable (default: temperature_2m)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Hours back to generate timestamps (default: 24)",
    )
    parser.add_argument(
        "--format",
        choices=["plain", "curl", "curl-output"],
        default="plain",
        help="Output format (default: plain)",
    )
    parser.add_argument(
        "--titiler-url",
        default=TITILER_BASE_URL,
        help=f"TiTiler base URL (default: {TITILER_BASE_URL})",
    )
    parser.add_argument(
        "--all-variables",
        action="store_true",
        help="Generate URLs for all variables",
    )
    parser.add_argument(
        "--endpoint",
        choices=["tile", "info", "tilejson", "statistics", "preview", "point", "all"],
        default="all",
        help="Which endpoint to generate URLs for (default: all)",
    )
    args = parser.parse_args()

    # Get timestamps
    timestamps = get_recent_timestamps(args.hours)
    if not timestamps:
        print("No timestamps generated")
        return

    # Select variables
    variables = VARIABLES if args.all_variables else [args.variable]

    print(f"# TiTiler Sample URLs")
    print(f"# Generated: {datetime.utcnow().isoformat()}Z")
    print(f"# TiTiler URL: {args.titiler_url}")
    print()

    for variable in variables:
        print(f"# Variable: {variable}")
        print(f"# {'='*50}")

        # Use most recent timestamp
        timestamp = timestamps[0]
        cog_url = generate_cog_url(variable, timestamp)

        print(f"\n# COG URL: {cog_url}")

        if args.endpoint in ["tilejson", "all"]:
            print(f"\n# TileJSON endpoint (get tile URL template):")
            print_urls([generate_tilejson_url(cog_url, args.titiler_url)], args.format)

        if args.endpoint in ["info", "all"]:
            print(f"\n# Info endpoint:")
            print_urls([generate_info_url(cog_url, args.titiler_url)], args.format)

        if args.endpoint in ["statistics", "all"]:
            print(f"\n# Statistics endpoint:")
            print_urls([generate_statistics_url(cog_url, args.titiler_url)], args.format)

        if args.endpoint in ["preview", "all"]:
            print(f"\n# Preview endpoint:")
            print_urls([generate_preview_url(cog_url, titiler_url=args.titiler_url)], args.format)

        if args.endpoint in ["point", "all"]:
            print(f"\n# Point query (Columbus, OH):")
            print_urls([generate_point_url(cog_url, -83.0, 40.0, args.titiler_url)], args.format)

        if args.endpoint in ["tile", "all"]:
            print(f"\n# Tile endpoints:")
            tile_urls = [
                generate_tile_url(cog_url, z, x, y, args.titiler_url)
                for z, x, y in SAMPLE_TILES
            ]
            print_urls(tile_urls, args.format)

        print()

    # Print available timestamps
    print(f"\n# Available timestamps (last {args.hours} hours):")
    for ts in timestamps[:8]:
        print(f"#   {ts['display']}")
    if len(timestamps) > 8:
        print(f"#   ... and {len(timestamps) - 8} more")


if __name__ == "__main__":
    main()
