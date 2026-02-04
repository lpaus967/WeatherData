#!/usr/bin/env python3
"""
TBOFS Pipeline - Download, Process, and Upload

Unified script to run the full TBOFS pipeline with options to select
which data products to process.

Usage:
    # Currents only (download + process + upload to Mapbox)
    python run_tbofs_pipeline.py --latest --currents
    
    # Temperature only (download + process for S3)
    python run_tbofs_pipeline.py --latest --temperature
    
    # Both
    python run_tbofs_pipeline.py --latest --currents --temperature
    
    # Currents with custom options
    python run_tbofs_pipeline.py --latest --currents --hours 1-6 --upload
"""

import argparse
import subprocess
import sys
from pathlib import Path
from datetime import datetime


def run_command(cmd: list, description: str) -> bool:
    """Run a command and return success status."""
    print(f"\n{'='*60}")
    print(f"▶ {description}")
    print(f"{'='*60}")
    print(f"$ {' '.join(cmd)}\n")
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print(f"✓ {description} - Complete")
        return True
    else:
        print(f"✗ {description} - Failed (exit code {result.returncode})")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='TBOFS Pipeline - Download, Process, and Upload',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Ocean currents only (for Mapbox raster-particle)
  python run_tbofs_pipeline.py --latest --currents --upload
  
  # Temperature only (for S3 tiles)
  python run_tbofs_pipeline.py --latest --temperature --colorize
  
  # Both products, first 6 hours
  python run_tbofs_pipeline.py --latest --currents --temperature --hours 1-6
  
  # Specific date
  python run_tbofs_pipeline.py --date 2026-02-04 --cycle 00 --currents
        """
    )
    
    # Date selection
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument('--latest', action='store_true',
                           help='Use latest available forecast')
    date_group.add_argument('--date', type=str,
                           help='Specific date (YYYY-MM-DD)')
    
    parser.add_argument('--cycle', type=int, choices=[0, 6, 12, 18],
                        help='Model cycle (required with --date)')
    parser.add_argument('--hours', type=str, default='1-6',
                        help='Forecast hours (default: 1-6)')
    
    # Product selection
    parser.add_argument('--currents', action='store_true',
                        help='Process ocean currents (u/v)')
    parser.add_argument('--temperature', action='store_true',
                        help='Process sea surface temperature')
    
    # Processing options
    parser.add_argument('--upload', action='store_true',
                        help='Upload currents to Mapbox')
    parser.add_argument('--colorize', action='store_true',
                        help='Create colored temperature images')
    parser.add_argument('--tileset', type=str, default='tbofs_currents',
                        help='Mapbox tileset name (default: tbofs_currents)')
    
    # Directories
    parser.add_argument('--work-dir', type=Path, default=Path('/tmp/tbofs-pipeline'),
                        help='Working directory (default: /tmp/tbofs-pipeline)')
    parser.add_argument('--keep-files', action='store_true',
                        help='Keep intermediate files')
    
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.currents and not args.temperature:
        parser.error("At least one of --currents or --temperature is required")
    
    if args.date and not args.cycle:
        parser.error("--cycle is required with --date")
    
    # Get script directory
    script_dir = Path(__file__).parent
    
    # Setup directories
    download_dir = args.work_dir / "raw"
    currents_dir = args.work_dir / "currents"
    temp_dir = args.work_dir / "temperature"
    
    print("=" * 60)
    print("TBOFS Pipeline")
    print("=" * 60)
    print(f"Products: {'currents ' if args.currents else ''}{'temperature' if args.temperature else ''}")
    print(f"Hours: {args.hours}")
    print(f"Work dir: {args.work_dir}")
    if args.upload:
        print(f"Upload to: mapbox://onwaterllc.{args.tileset}")
    
    # Step 1: Download
    download_cmd = [
        sys.executable, str(script_dir / "download_tbofs.py"),
        '--hours', args.hours,
        '-o', str(download_dir)
    ]
    
    if args.latest:
        download_cmd.append('--latest')
    else:
        download_cmd.extend(['--date', args.date, '--cycle', str(args.cycle)])
    
    if args.verbose:
        download_cmd.append('-v')
    
    if not run_command(download_cmd, "Download TBOFS data"):
        return 1
    
    # Step 2: Process currents
    if args.currents:
        currents_cmd = [
            sys.executable, str(script_dir / "process_tbofs_currents.py"),
            '-i', str(download_dir),
            '-o', str(currents_dir),
            '--hours', args.hours
        ]
        
        if args.verbose:
            currents_cmd.append('-v')
        
        if not run_command(currents_cmd, "Process ocean currents"):
            return 1
        
        # Step 3: Upload currents to Mapbox
        if args.upload:
            upload_cmd = [
                sys.executable, str(script_dir / "upload_tbofs_currents.py"),
                '-i', str(currents_dir / "geotiff"),
                '--tileset', args.tileset
            ]
            
            if args.verbose:
                upload_cmd.append('-v')
            
            if not run_command(upload_cmd, "Upload currents to Mapbox"):
                return 1
    
    # Step 4: Process temperature
    if args.temperature:
        temp_cmd = [
            sys.executable, str(script_dir / "process_tbofs_temperature.py"),
            '-i', str(download_dir),
            '-o', str(temp_dir),
            '--hours', args.hours
        ]
        
        if args.colorize:
            temp_cmd.append('--colorize')
        
        if args.verbose:
            temp_cmd.append('-v')
        
        if not run_command(temp_cmd, "Process sea surface temperature"):
            return 1
    
    # Summary
    print(f"\n{'='*60}")
    print("Pipeline Complete!")
    print(f"{'='*60}")
    
    if args.currents:
        print(f"  Currents: {currents_dir}/geotiff/")
        if args.upload:
            print(f"  Mapbox: mapbox://onwaterllc.{args.tileset}")
    
    if args.temperature:
        print(f"  Temperature: {temp_dir}/")
    
    # Cleanup hint
    if not args.keep_files:
        print(f"\nTo clean up: rm -rf {args.work_dir}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
