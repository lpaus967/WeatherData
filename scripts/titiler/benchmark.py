#!/usr/bin/env python3
"""
TiTiler Performance Benchmark

Compares TiTiler dynamic tile generation performance with pre-generated S3 tiles.

Usage:
    python benchmark.py
    python benchmark.py --iterations 20
    python benchmark.py --output results.json
"""

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

import requests


# Configuration
DEFAULT_TITILER_URL = "http://localhost:8000"
S3_BUCKET = "sat-data-automation-test"
S3_PREFIX = "processed-cogs"


class TileBenchmark:
    """Benchmark tile generation performance."""

    def __init__(self, titiler_url: str, iterations: int = 10):
        self.titiler_url = titiler_url.rstrip("/")
        self.iterations = iterations
        self.results = {}

    def get_recent_cog_url(self, variable: str = "temperature_2m") -> str:
        """Generate a COG URL that should exist."""
        recent_date = datetime.utcnow() - timedelta(days=6)
        hour = (recent_date.hour // 6) * 6

        year = recent_date.strftime("%Y")
        month = recent_date.strftime("%m")
        day = recent_date.strftime("%d")
        date_compact = recent_date.strftime("%Y%m%d")

        filename = f"{variable}_hrrr.{date_compact}.t{hour:02d}z.f00.tif"
        return f"s3://{S3_BUCKET}/{S3_PREFIX}/{year}/{month}/{day}/{filename}"

    def get_tile_url(self, cog_url: str, z: int, x: int, y: int) -> str:
        """Generate tile URL with WebMercatorQuad format."""
        return f"{self.titiler_url}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png?url={quote(cog_url, safe='')}"

    def benchmark_single_tile(
        self,
        z: int,
        x: int,
        y: int,
        cog_url: str,
    ) -> dict:
        """Benchmark a single tile request."""
        url = self.get_tile_url(cog_url, z, x, y)

        times = []
        sizes = []
        errors = 0

        for i in range(self.iterations):
            try:
                start = time.time()
                response = requests.get(url, timeout=120)
                elapsed = time.time() - start

                if response.status_code == 200:
                    times.append(elapsed)
                    sizes.append(len(response.content))
                else:
                    errors += 1
            except Exception as e:
                errors += 1

        if times:
            return {
                "tile": f"{z}/{x}/{y}",
                "iterations": self.iterations,
                "successful": len(times),
                "errors": errors,
                "mean_time": statistics.mean(times),
                "median_time": statistics.median(times),
                "min_time": min(times),
                "max_time": max(times),
                "std_dev": statistics.stdev(times) if len(times) > 1 else 0,
                "mean_size": statistics.mean(sizes),
            }
        else:
            return {
                "tile": f"{z}/{x}/{y}",
                "iterations": self.iterations,
                "successful": 0,
                "errors": errors,
                "error": "All requests failed",
            }

    def benchmark_zoom_levels(self, cog_url: str) -> list[dict]:
        """Benchmark tiles at different zoom levels."""
        # Tile coordinates within CONUS bounds
        tiles = [
            (2, 0, 1),    # Very low zoom
            (3, 1, 3),    # Low zoom
            (4, 3, 6),    # Medium zoom
            (5, 7, 12),   # Higher zoom
        ]

        results = []
        for z, x, y in tiles:
            print(f"  Benchmarking zoom {z} (tile {z}/{x}/{y})...")
            result = self.benchmark_single_tile(z, x, y, cog_url)
            results.append(result)
            if "mean_time" in result:
                print(f"    Mean: {result['mean_time']:.3f}s, "
                      f"Min: {result['min_time']:.3f}s, "
                      f"Max: {result['max_time']:.3f}s")
            else:
                print(f"    FAILED: {result.get('error', 'Unknown error')}")

        return results

    def benchmark_concurrent_requests(
        self,
        cog_url: str,
        num_requests: int = 10,
        workers: int = 5,
    ) -> dict:
        """Benchmark concurrent tile requests."""
        # Generate different tile coordinates
        tiles = [
            (4, 2 + i % 4, 5 + i % 4)
            for i in range(num_requests)
        ]

        urls = [
            self.get_tile_url(cog_url, z, x, y)
            for z, x, y in tiles
        ]

        def fetch_tile(url: str) -> tuple[float, int, bool]:
            try:
                start = time.time()
                response = requests.get(url, timeout=120)
                elapsed = time.time() - start
                return elapsed, len(response.content), response.status_code == 200
            except Exception:
                return 0, 0, False

        print(f"  Running {num_requests} concurrent requests with {workers} workers...")
        start_time = time.time()

        times = []
        successes = 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(fetch_tile, url) for url in urls]
            for future in as_completed(futures):
                elapsed, size, success = future.result()
                if success:
                    times.append(elapsed)
                    successes += 1

        total_time = time.time() - start_time

        return {
            "total_requests": num_requests,
            "workers": workers,
            "successful": successes,
            "total_time": total_time,
            "requests_per_second": successes / total_time if total_time > 0 else 0,
            "mean_time": statistics.mean(times) if times else 0,
            "median_time": statistics.median(times) if times else 0,
        }

    def benchmark_cold_vs_warm(self, cog_url: str) -> dict:
        """Compare cold start vs warm cache performance."""
        z, x, y = 4, 3, 6
        url = self.get_tile_url(cog_url, z, x, y)

        # Cold request (first request)
        print("  Cold start request...")
        start = time.time()
        response1 = requests.get(url, timeout=120)
        cold_time = time.time() - start

        if response1.status_code != 200:
            return {"error": f"Tile request failed: {response1.status_code}"}

        # Warm requests
        print("  Warm cache requests...")
        warm_times = []
        for _ in range(5):
            start = time.time()
            response = requests.get(url, timeout=120)
            warm_times.append(time.time() - start)

        return {
            "cold_time": cold_time,
            "warm_mean": statistics.mean(warm_times),
            "warm_min": min(warm_times),
            "warm_max": max(warm_times),
            "speedup": cold_time / statistics.mean(warm_times) if warm_times else 0,
        }

    def run_full_benchmark(self) -> dict:
        """Run complete benchmark suite."""
        print("\n" + "=" * 60)
        print("TiTiler Performance Benchmark")
        print(f"Base URL: {self.titiler_url}")
        print(f"Iterations per test: {self.iterations}")
        print(f"Timestamp: {datetime.utcnow().isoformat()}Z")
        print("=" * 60)

        cog_url = self.get_recent_cog_url()
        print(f"\nTest COG: {cog_url}")

        results = {
            "config": {
                "titiler_url": self.titiler_url,
                "iterations": self.iterations,
                "cog_url": cog_url,
                "timestamp": datetime.utcnow().isoformat(),
            },
        }

        # 1. Zoom level benchmarks
        print("\n1. Zoom Level Performance")
        print("-" * 40)
        results["zoom_levels"] = self.benchmark_zoom_levels(cog_url)

        # 2. Cold vs warm
        print("\n2. Cold Start vs Warm Cache")
        print("-" * 40)
        results["cold_warm"] = self.benchmark_cold_vs_warm(cog_url)
        if "error" not in results["cold_warm"]:
            print(f"  Cold: {results['cold_warm']['cold_time']:.3f}s")
            print(f"  Warm mean: {results['cold_warm']['warm_mean']:.3f}s")
            print(f"  Speedup: {results['cold_warm']['speedup']:.1f}x")

        # 3. Concurrent requests
        print("\n3. Concurrent Request Performance")
        print("-" * 40)
        results["concurrent"] = self.benchmark_concurrent_requests(cog_url)
        print(f"  Requests/sec: {results['concurrent']['requests_per_second']:.2f}")
        print(f"  Mean latency: {results['concurrent']['mean_time']:.3f}s")

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)

        zoom_results = [r for r in results["zoom_levels"] if "mean_time" in r]
        if zoom_results:
            all_means = [r["mean_time"] for r in zoom_results]
            print(f"Average tile latency: {statistics.mean(all_means):.3f}s")
            print(f"Fastest zoom level: {min(zoom_results, key=lambda x: x['mean_time'])['tile']}")
            print(f"Slowest zoom level: {max(zoom_results, key=lambda x: x['mean_time'])['tile']}")

        print(f"Throughput: {results['concurrent']['requests_per_second']:.2f} req/s")

        return results


def main():
    parser = argparse.ArgumentParser(description="Benchmark TiTiler performance")
    parser.add_argument(
        "--titiler-url",
        default=DEFAULT_TITILER_URL,
        help=f"TiTiler base URL (default: {DEFAULT_TITILER_URL})",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Number of iterations per test (default: 10)",
    )
    parser.add_argument(
        "--output",
        help="Output JSON file for results",
    )
    args = parser.parse_args()

    benchmark = TileBenchmark(args.titiler_url, args.iterations)
    results = benchmark.run_full_benchmark()

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
