#!/usr/bin/env python3
"""
TiTiler Test Suite

Tests TiTiler endpoints against existing COGs in S3 to validate:
- Health check endpoint
- COG info endpoint
- COG statistics endpoint
- Tile generation
- Point queries
- Preview generation

Usage:
    python test_titiler.py
    python test_titiler.py --base-url http://localhost:8000
    python test_titiler.py --verbose
    python test_titiler.py --cog-url "s3://bucket/path/to/file.tif"
    python test_titiler.py --date 2026-01-10 --hour 22
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import requests


# Configuration
DEFAULT_BASE_URL = "http://localhost:8000"
S3_BUCKET = "sat-data-automation-test"
S3_PREFIX = "processed-cogs"

# Test COG variables (matching actual file naming)
TEST_VARIABLES = [
    "temperature_2m",
    "dewpoint_2m",
    "wind_speed_10m",
    "total_cloud_cover",
]


class TiTilerTester:
    """Test suite for TiTiler endpoints."""

    def __init__(self, base_url: str, verbose: bool = False, cog_url: Optional[str] = None,
                 date_str: Optional[str] = None, hour: Optional[int] = None):
        self.base_url = base_url.rstrip("/")
        self.verbose = verbose
        self.results = []
        self.custom_cog_url = cog_url
        self.custom_date = date_str
        self.custom_hour = hour

    def log(self, message: str):
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(f"  {message}")

    def run_test(self, name: str, test_func) -> bool:
        """Run a single test and record result."""
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print("=" * 60)

        start_time = time.time()
        try:
            success, message = test_func()
            elapsed = time.time() - start_time

            if success:
                print(f"PASS ({elapsed:.2f}s): {message}")
            else:
                print(f"FAIL ({elapsed:.2f}s): {message}")

            self.results.append({
                "name": name,
                "success": success,
                "message": message,
                "elapsed": elapsed,
            })
            return success

        except Exception as e:
            elapsed = time.time() - start_time
            print(f"ERROR ({elapsed:.2f}s): {str(e)}")
            self.results.append({
                "name": name,
                "success": False,
                "message": str(e),
                "elapsed": elapsed,
            })
            return False

    def get_recent_cog_url(self, variable: str = "temperature_2m", forecast_hour: int = 0) -> str:
        """
        Generate a COG URL that should exist.
        Uses custom date/hour if provided, otherwise uses a recent date/time.

        Path format: s3://{bucket}/processed-cogs/YYYY/MM/DD/{variable}_hrrr.YYYYMMDD.tHHz.fFF.tif
        """
        # If custom COG URL provided and this is temperature (default), use it
        if self.custom_cog_url and variable == "temperature_2m":
            return self.custom_cog_url

        # Use custom date/hour if provided
        if self.custom_date and self.custom_hour is not None:
            date_parts = self.custom_date.split("-")
            year, month, day = date_parts[0], date_parts[1], date_parts[2]
            date_compact = f"{year}{month}{day}"
            hour = self.custom_hour
        else:
            # Use a date from a few days ago to ensure data exists
            recent_date = datetime.now(timezone.utc) - timedelta(days=6)
            # Round to 6-hour interval (00, 06, 12, 18)
            hour = (recent_date.hour // 6) * 6
            year = recent_date.strftime("%Y")
            month = recent_date.strftime("%m")
            day = recent_date.strftime("%d")
            date_compact = recent_date.strftime("%Y%m%d")

        filename = f"{variable}_hrrr.{date_compact}.t{hour:02d}z.f{forecast_hour:02d}.tif"
        return f"s3://{S3_BUCKET}/{S3_PREFIX}/{year}/{month}/{day}/{filename}"

    def get_tile_url(self, cog_url: str, z: int, x: int, y: int) -> str:
        """Generate tile URL with correct WebMercatorQuad format."""
        return f"{self.base_url}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png?url={quote(cog_url, safe='')}"

    # =========================================================================
    # Test Methods
    # =========================================================================

    def test_health(self) -> tuple[bool, str]:
        """Test the health endpoint."""
        url = f"{self.base_url}/healthz"
        self.log(f"GET {url}")

        response = requests.get(url, timeout=10)
        self.log(f"Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            version = data.get("versions", {}).get("titiler", "unknown")
            return True, f"Health endpoint responding (TiTiler v{version})"
        return False, f"Health check failed with status {response.status_code}"

    def test_cog_info(self) -> tuple[bool, str]:
        """Test the COG info endpoint."""
        cog_url = self.get_recent_cog_url()
        url = f"{self.base_url}/cog/info?url={quote(cog_url, safe='')}"
        self.log(f"GET {url}")
        self.log(f"COG: {cog_url}")

        response = requests.get(url, timeout=30)
        self.log(f"Status: {response.status_code}")

        if response.status_code != 200:
            return False, f"Info request failed with status {response.status_code}: {response.text[:200]}"

        data = response.json()
        self.log(f"Response: {json.dumps(data, indent=2)[:500]}")

        # Validate expected fields
        required_fields = ["bounds", "crs", "dtype"]
        missing = [f for f in required_fields if f not in data]
        if missing:
            return False, f"Missing fields in response: {missing}"

        bounds = data.get("bounds", [])
        crs = data.get("crs", "unknown")
        return True, f"COG info retrieved. CRS: {crs}"

    def test_cog_statistics(self) -> tuple[bool, str]:
        """Test the COG statistics endpoint."""
        cog_url = self.get_recent_cog_url()
        url = f"{self.base_url}/cog/statistics?url={quote(cog_url, safe='')}"
        self.log(f"GET {url}")

        response = requests.get(url, timeout=30)
        self.log(f"Status: {response.status_code}")

        if response.status_code != 200:
            return False, f"Statistics request failed: {response.status_code}"

        data = response.json()
        self.log(f"Response: {json.dumps(data, indent=2)[:500]}")

        # Check we got band statistics
        if not data:
            return False, "No statistics returned"

        # Get first band stats
        first_band = list(data.values())[0] if isinstance(data, dict) else data[0]
        if "min" in first_band and "max" in first_band:
            return True, f"Statistics retrieved. Min: {first_band['min']:.2f}, Max: {first_band['max']:.2f}"

        return True, "Statistics endpoint responding"

    def test_tile_generation(self) -> tuple[bool, str]:
        """Test tile generation endpoint."""
        cog_url = self.get_recent_cog_url()

        # Use a tile that should be within CONUS bounds at zoom 4
        z, x, y = 4, 3, 6

        url = self.get_tile_url(cog_url, z, x, y)
        self.log(f"GET {url}")

        response = requests.get(url, timeout=60)
        self.log(f"Status: {response.status_code}")
        self.log(f"Content-Type: {response.headers.get('content-type')}")
        self.log(f"Content-Length: {len(response.content)} bytes")

        if response.status_code != 200:
            return False, f"Tile request failed: {response.status_code} - {response.text[:200]}"

        # Check we got an image
        content_type = response.headers.get("content-type", "")
        if "image" not in content_type:
            return False, f"Unexpected content type: {content_type}"

        # Check reasonable size (not empty, not too small)
        if len(response.content) < 100:
            return False, f"Tile too small ({len(response.content)} bytes), may be empty"

        return True, f"Tile generated successfully ({len(response.content)} bytes)"

    def test_multiple_tiles(self) -> tuple[bool, str]:
        """Test generating multiple tiles to check consistency."""
        cog_url = self.get_recent_cog_url()
        # Tiles within CONUS bounds (zoom 2-5 based on TileJSON)
        tiles = [
            (2, 0, 1),   # Low zoom
            (3, 1, 3),   # Lower zoom
            (4, 3, 6),   # Mid zoom
            (5, 7, 12),  # Higher zoom
        ]

        results = []
        for z, x, y in tiles:
            url = self.get_tile_url(cog_url, z, x, y)
            self.log(f"GET tile z={z}, x={x}, y={y}")

            response = requests.get(url, timeout=60)
            results.append({
                "tile": f"{z}/{x}/{y}",
                "status": response.status_code,
                "size": len(response.content),
            })

        successes = [r for r in results if r["status"] == 200]
        if len(successes) == len(tiles):
            sizes = [r["size"] for r in results]
            return True, f"All {len(tiles)} tiles generated. Sizes: {sizes}"
        else:
            failures = [r for r in results if r["status"] != 200]
            return False, f"{len(failures)} tiles failed: {failures}"

    def test_point_query(self) -> tuple[bool, str]:
        """Test point value query."""
        cog_url = self.get_recent_cog_url()

        # Query a point in central US (Columbus, OH area)
        lon, lat = -83.0, 40.0

        # TiTiler uses comma separator for coordinates: /point/{lon},{lat}
        url = f"{self.base_url}/cog/point/{lon},{lat}?url={quote(cog_url, safe='')}"
        self.log(f"GET {url}")

        response = requests.get(url, timeout=30)
        self.log(f"Status: {response.status_code}")

        if response.status_code != 200:
            return False, f"Point query failed: {response.status_code}"

        data = response.json()
        self.log(f"Response: {data}")

        if "values" in data:
            return True, f"Point query successful. Values: {data['values']}"
        elif "coordinates" in data:
            return True, f"Point query successful. Response: {data}"

        return True, "Point query endpoint responding"

    def test_preview(self) -> tuple[bool, str]:
        """Test preview image generation."""
        cog_url = self.get_recent_cog_url()

        url = f"{self.base_url}/cog/preview?url={quote(cog_url, safe='')}&max_size=256"
        self.log(f"GET {url}")

        response = requests.get(url, timeout=60)
        self.log(f"Status: {response.status_code}")
        self.log(f"Content-Length: {len(response.content)} bytes")

        if response.status_code != 200:
            return False, f"Preview request failed: {response.status_code}"

        # 100 bytes is a reasonable minimum for a valid PNG
        if len(response.content) < 100:
            return False, f"Preview too small ({len(response.content)} bytes)"

        return True, f"Preview generated ({len(response.content)} bytes)"

    def test_multiple_variables(self) -> tuple[bool, str]:
        """Test COG info for multiple weather variables."""
        results = []

        for variable in TEST_VARIABLES:
            cog_url = self.get_recent_cog_url(variable)
            url = f"{self.base_url}/cog/info?url={quote(cog_url, safe='')}"
            self.log(f"Testing {variable}: {cog_url}")

            try:
                response = requests.get(url, timeout=30)
                results.append({
                    "variable": variable,
                    "status": response.status_code,
                    "success": response.status_code == 200,
                })
            except Exception as e:
                results.append({
                    "variable": variable,
                    "status": "error",
                    "success": False,
                    "error": str(e),
                })

        successes = [r for r in results if r["success"]]
        if len(successes) > 0:
            variables = [r["variable"] for r in successes]
            return True, f"{len(successes)}/{len(results)} variables accessible: {variables}"
        else:
            return False, "No variables accessible"

    def test_tile_performance(self) -> tuple[bool, str]:
        """Benchmark tile generation performance."""
        cog_url = self.get_recent_cog_url()
        z, x, y = 4, 3, 6

        url = self.get_tile_url(cog_url, z, x, y)

        # First request (cold)
        start = time.time()
        response1 = requests.get(url, timeout=60)
        cold_time = time.time() - start

        if response1.status_code != 200:
            return False, f"Tile request failed: {response1.status_code}"

        # Second request (warm, potentially cached)
        start = time.time()
        response2 = requests.get(url, timeout=60)
        warm_time = time.time() - start

        return True, f"Cold: {cold_time:.2f}s, Warm: {warm_time:.2f}s"

    def test_tilejson(self) -> tuple[bool, str]:
        """Test TileJSON endpoint for tile URL discovery."""
        cog_url = self.get_recent_cog_url()
        url = f"{self.base_url}/cog/WebMercatorQuad/tilejson.json?url={quote(cog_url, safe='')}"
        self.log(f"GET {url}")

        response = requests.get(url, timeout=30)
        self.log(f"Status: {response.status_code}")

        if response.status_code != 200:
            return False, f"TileJSON request failed: {response.status_code}"

        data = response.json()

        minzoom = data.get("minzoom", "?")
        maxzoom = data.get("maxzoom", "?")
        bounds = data.get("bounds", [])

        return True, f"TileJSON retrieved. Zoom: {minzoom}-{maxzoom}, Bounds: {bounds}"

    # =========================================================================
    # Run All Tests
    # =========================================================================

    def run_all_tests(self) -> bool:
        """Run all tests and return overall success."""
        print("\n" + "=" * 60)
        print("TiTiler Test Suite")
        print(f"Base URL: {self.base_url}")
        print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
        if self.custom_cog_url:
            print(f"Custom COG URL: {self.custom_cog_url}")
        elif self.custom_date:
            print(f"Custom date/hour: {self.custom_date} t{self.custom_hour:02d}z")
        print("=" * 60)

        # Run tests in order
        tests = [
            ("Health Check", self.test_health),
            ("TileJSON", self.test_tilejson),
            ("COG Info", self.test_cog_info),
            ("COG Statistics", self.test_cog_statistics),
            ("Single Tile Generation", self.test_tile_generation),
            ("Multiple Tiles", self.test_multiple_tiles),
            ("Point Query", self.test_point_query),
            ("Preview Generation", self.test_preview),
            ("Multiple Variables", self.test_multiple_variables),
            ("Tile Performance", self.test_tile_performance),
        ]

        for name, test_func in tests:
            self.run_test(name, test_func)

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)

        passed = sum(1 for r in self.results if r["success"])
        failed = len(self.results) - passed
        total_time = sum(r["elapsed"] for r in self.results)

        print(f"Passed: {passed}/{len(self.results)}")
        print(f"Failed: {failed}/{len(self.results)}")
        print(f"Total time: {total_time:.2f}s")

        if failed > 0:
            print("\nFailed tests:")
            for r in self.results:
                if not r["success"]:
                    print(f"  - {r['name']}: {r['message']}")

        return failed == 0


def main():
    parser = argparse.ArgumentParser(description="Test TiTiler endpoints")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"TiTiler base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--cog-url",
        help="Specific COG URL to test (overrides date/hour for primary tests)",
    )
    parser.add_argument(
        "--date",
        help="Date to test (format: YYYY-MM-DD), e.g., 2026-01-10",
    )
    parser.add_argument(
        "--hour",
        type=int,
        choices=[0, 6, 12, 18, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 19, 20, 21, 22, 23],
        help="Hour to test (0-23), e.g., 22 for t22z",
    )
    args = parser.parse_args()

    # Validate date/hour are provided together
    if (args.date and args.hour is None) or (args.hour is not None and not args.date):
        parser.error("--date and --hour must be provided together")

    tester = TiTilerTester(
        args.base_url,
        args.verbose,
        cog_url=args.cog_url,
        date_str=args.date,
        hour=args.hour,
    )
    success = tester.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
