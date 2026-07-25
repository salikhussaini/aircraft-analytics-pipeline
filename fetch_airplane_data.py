"""
Fetch real-time airplane data from OpenSky Network API (free)

OpenSky Network provides free access to real-time aircraft tracking data.
No API key required for basic usage (though there are rate limits).

Usage:
    python fetch_airplane_data.py              # Fetch all aircraft once (saves to parquet)
    python fetch_airplane_data.py --count 10   # Fetch first 10 aircraft
    python fetch_airplane_data.py --bounds     # Fetch from specific region
    python fetch_airplane_data.py --schedule 0.5  # Fetch twice per hour (daemon mode, saves to parquet)
    python fetch_airplane_data.py --output csv # Fetch to CSV instead
"""

import requests
import json
import argparse
import csv
import time
import schedule
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime
import sys

try:
    import polars as pl
    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False


def setup_logging():
    """
    Set up logging to both console and file.
    Logs are saved to logs/ folder with datetime-based filenames.
    """
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Create logger
    logger = logging.getLogger("airplane_fetcher")
    logger.setLevel(logging.DEBUG)
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # Log file path with datetime
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = logs_dir / f"fetch_{timestamp}.log"
    
    # Console handler (INFO level - user-friendly)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_format)
    try:
        console_handler.stream.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    
    # File handler (DEBUG level - detailed)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10_485_760,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)
    
    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger


logger = setup_logging()


class AirplaneDataFetcher:
    """Fetch airplane data from OpenSky Network API"""
    
    # OpenSky Network API endpoints (free tier)
    BASE_URL = "https://opensky-network.org/api"
    STATES_ENDPOINT = f"{BASE_URL}/states/all"
    
    # Default bounding box (world coverage): [min_lat, max_lat, min_lon, max_lon]
    # You can modify these to fetch specific regions
    DEFAULT_BOUNDS = None  # None = all aircraft
    
    # Rate limit info: free tier allows ~4000 requests/hour
    RATE_LIMIT_WARNING = "Note: Free tier is limited to ~4000 requests/hour"
    
    # Data directory
    DATA_DIR = Path("data")
    
    def __init__(self, timeout: int = 10):
        """Initialize fetcher with timeout"""
        self.timeout = timeout
        self.session = requests.Session()
        # Create data directory if it doesn't exist
        self.DATA_DIR.mkdir(exist_ok=True)
    
    def fetch_all_aircraft(
        self,
        bounds: Optional[List[float]] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Fetch all currently visible aircraft
        
        Args:
            bounds: [min_lat, max_lat, min_lon, max_lon] or None for world
            limit: Maximum number of aircraft to return
            
        Returns:
            List of aircraft data dictionaries
        """
        try:
            params = {}
            if bounds:
                # Format: lamin, lamax, lomin, lomax
                params['lamin'] = bounds[0]
                params['lamax'] = bounds[1]
                params['lomin'] = bounds[2]
                params['lomax'] = bounds[3]
            
            logger.info(f"Fetching aircraft data from OpenSky Network...")
            response = self.session.get(
                self.STATES_ENDPOINT,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            logger.debug(f"API request successful, status code: {response.status_code}")
            
            data = response.json()
            
            # OpenSky returns: [time, states] where states is list of aircraft
            states = data.get('states', [])
            
            if not states:
                logger.warning("No aircraft currently visible.")
                return []
            
            # Convert to list of dictionaries
            aircraft_list = []
            for state in states:
                aircraft = {
                    'icao24': state[0],              # ICAO 24-bit address
                    'callsign': state[1],           # Callsign
                    'origin_country': state[2],     # Country of origin
                    'time_position': state[3],      # Last time position was updated
                    'last_contact': state[4],       # Last contact time
                    'longitude': state[5],          # Longitude
                    'latitude': state[6],           # Latitude
                    'baro_altitude': state[7],      # Barometric altitude in meters
                    'on_ground': state[8],          # True if on ground
                    'velocity': state[9],           # Velocity in m/s
                    'true_track': state[10],        # True track (heading)
                    'vertical_rate': state[11],     # Vertical rate in m/s
                    'sensors': state[12] if len(state) > 12 else None,           # Receiver IDs
                    'geo_altitude': state[13] if len(state) > 13 else None,      # Geometric altitude
                    'squawk': state[14] if len(state) > 14 else None,            # Transponder code
                    'spi': state[15] if len(state) > 15 else None,               # Special purpose indicator
                    'position_source': state[16] if len(state) > 16 else None,   # Position source (0=ADS-B, 1=ASTERIX, 2=MLAT, 3=FLARM)
                    'category': state[17] if len(state) > 17 else None,          # Aircraft category
                }
                aircraft_list.append(aircraft)
            
            if limit:
                aircraft_list = aircraft_list[:limit]
            
            return aircraft_list
        
        except requests.exceptions.Timeout:
            logger.error(f"Request timed out (>{self.timeout}s)")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching data: {e}")
            return []
    
    def format_aircraft(self, aircraft: Dict) -> str:
        """Format aircraft data for display"""
        callsign = (aircraft['callsign'] or '').strip() or 'N/A'
        country = str(aircraft['origin_country'] or 'Unknown')
        lat = aircraft['latitude'] or 0
        lon = aircraft['longitude'] or 0
        alt = aircraft['baro_altitude']
        velocity = aircraft['velocity']
        on_ground = "On Ground" if aircraft['on_ground'] else "In Flight"
        
        alt_str = f"{int(alt)}m" if alt is not None else "Unknown"
        vel_str = f"{velocity:.1f}m/s" if velocity is not None else "Unknown"
        
        return (
            f"✈️  {callsign:10} | {country:20} | "
            f"Pos: ({lat:.2f}, {lon:.2f}) | Alt: {alt_str:8} | "
            f"Speed: {vel_str:10} | {on_ground}"
        )
    
    def print_aircraft_data(self, aircraft_list: List[Dict], verbose: bool = False):
        """Pretty print aircraft data"""
        if not aircraft_list:
            logger.info("No aircraft data to display.")
            return
        
        logger.info(f"\n{'='*150}")
        logger.info(f"Found {len(aircraft_list)} aircraft")
        logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{self.RATE_LIMIT_WARNING}")
        logger.info(f"{'='*150}\n")
        
        for i, aircraft in enumerate(aircraft_list, 1):
            logger.info(f"{i}. {self.format_aircraft(aircraft)}")
            
            if verbose:
                logger.debug(f"   ICAO24: {aircraft['icao24']}")
                logger.debug(f"   Vertical Rate: {aircraft['vertical_rate']} m/s")
    
    def save_to_csv(self, aircraft_list: List[Dict], filename: str = "aircraft_data.csv"):
        """Save aircraft data to CSV file with timestamp"""
        if not aircraft_list:
            return
        
        file_path = self.DATA_DIR / filename
        file_exists = file_path.exists()
        
        try:
            with open(file_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        'timestamp', 'icao24', 'callsign', 'origin_country',
                        'latitude', 'longitude', 'baro_altitude', 'geo_altitude',
                        'velocity', 'on_ground', 'vertical_rate', 'true_track',
                        'time_position', 'last_contact', 'sensors', 'squawk',
                        'spi', 'position_source', 'category'
                    ]
                )
                
                if not file_exists:
                    writer.writeheader()
                
                for aircraft in aircraft_list:
                    row = {
                        'timestamp': datetime.now().isoformat(),
                        'icao24': aircraft['icao24'],
                        'callsign': aircraft['callsign'],
                        'origin_country': aircraft['origin_country'],
                        'latitude': aircraft['latitude'],
                        'longitude': aircraft['longitude'],
                        'baro_altitude': aircraft['baro_altitude'],
                        'geo_altitude': aircraft['geo_altitude'],
                        'velocity': aircraft['velocity'],
                        'on_ground': aircraft['on_ground'],
                        'vertical_rate': aircraft['vertical_rate'],
                        'true_track': aircraft['true_track'],
                        'time_position': aircraft['time_position'],
                        'last_contact': aircraft['last_contact'],
                        'sensors': aircraft['sensors'],
                        'squawk': aircraft['squawk'],
                        'spi': aircraft['spi'],
                        'position_source': aircraft['position_source'],
                        'category': aircraft['category']
                    }
                    writer.writerow(row)
            
            logger.info(f"✓ Saved {len(aircraft_list)} aircraft to {file_path}")
            logger.debug(f"CSV save successful: {len(aircraft_list)} rows appended")
            
        except IOError as e:
            logger.error(f"Error saving to {file_path}: {e}")
    
    def save_to_json(self, aircraft_list: List[Dict], filename: str = "aircraft_data.json"):
        """Save aircraft data to JSON file with timestamp"""
        if not aircraft_list:
            return
        
        try:
            file_path = self.DATA_DIR / filename
            
            data = {
                'timestamp': datetime.now().isoformat(),
                'aircraft_count': len(aircraft_list),
                'aircraft': aircraft_list
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"✓ Saved {len(aircraft_list)} aircraft to {file_path}")
            logger.debug(f"JSON save successful: {len(aircraft_list)} aircraft to {file_path}")
            
        except IOError as e:
            logger.error(f"Error saving to JSON: {e}")
    
    def save_to_parquet(self, aircraft_list: List[Dict], filename: str = "aircraft_data.parquet"):
        """Save aircraft data to Parquet file using Polars with datetime in filename"""
        if not aircraft_list:
            return
        
        if not POLARS_AVAILABLE:
            logger.error("Polars not installed. Install with: pip install polars")
            return
        
        try:
            # Add timestamp to each row
            for aircraft in aircraft_list:
                aircraft['timestamp'] = datetime.now().isoformat()
            
            # Create Polars DataFrame
            df = pl.DataFrame(aircraft_list)
            
            # Generate datetime-stamped filename
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            base_name = Path(filename).stem
            dated_filename = self.DATA_DIR / f"{base_name}_{timestamp}.parquet"
            
            # Write to parquet
            df.write_parquet(str(dated_filename))
            
            logger.info(f"✓ Saved {len(aircraft_list)} aircraft to {dated_filename}")
            logger.debug(f"Parquet save successful: {len(df)} rows, {len(df.columns)} columns")
            
        except Exception as e:
            logger.error(f"Error saving to parquet: {e}")


def fetch_and_save(
    fetcher: AirplaneDataFetcher,
    count: Optional[int],
    bounds: Optional[List[float]],
    output_format: str,
    verbose: bool
):
    """Fetch airplane data and save it"""
    aircraft_list = fetcher.fetch_all_aircraft(bounds=bounds, limit=count)
    
    if aircraft_list:
        fetcher.print_aircraft_data(aircraft_list, verbose=verbose)
        
        if output_format == 'csv':
            fetcher.save_to_csv(aircraft_list)
        elif output_format == 'json':
            fetcher.save_to_json(aircraft_list)
        elif output_format == 'parquet':
            fetcher.save_to_parquet(aircraft_list)
        elif output_format == 'both':
            fetcher.save_to_csv(aircraft_list)
            fetcher.save_to_json(aircraft_list)
        elif output_format == 'all':
            fetcher.save_to_csv(aircraft_list)
            fetcher.save_to_json(aircraft_list)
            fetcher.save_to_parquet(aircraft_list)


def run_scheduler(
    fetcher: AirplaneDataFetcher,
    interval: int,
    count: Optional[int],
    bounds: Optional[List[float]],
    output_format: str,
    verbose: bool
):
    """Run fetch job on schedule (daemon mode)"""
    logger.info(f"Starting scheduler to fetch data every {interval} hour(s)...")
    logger.info(f"Output format: {output_format}")
    logger.info("Press Ctrl+C to stop")
    logger.debug(f"Scheduler params - interval: {interval}h, bounds: {bounds}, count: {count}")
    
    # Initial fetch
    fetch_and_save(fetcher, count, bounds, output_format, verbose)
    
    # Schedule recurring fetches
    schedule.every(interval).hours.do(
        fetch_and_save,
        fetcher=fetcher,
        count=count,
        bounds=bounds,
        output_format=output_format,
        verbose=verbose
    )
    
    logger.info("Scheduler active, waiting for next scheduled run...")
    
    # Keep running
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check schedule every minute
    except KeyboardInterrupt:
        logger.warning("Scheduler interrupted by user (Ctrl+C)")
        logger.info("Scheduler stopped")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch real-time airplane data from OpenSky Network API (free)"
    )
    parser.add_argument(
        '--count',
        type=int,
        default=None,
        help='Limit number of aircraft to fetch'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed aircraft information'
    )
    parser.add_argument(
        '--bounds',
        type=float,
        nargs=4,
        metavar=('MIN_LAT', 'MAX_LAT', 'MIN_LON', 'MAX_LON'),
        help='Bounding box: min_lat, max_lat, min_lon, max_lon'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=10,
        help='Request timeout in seconds (default: 10)'
    )
    parser.add_argument(
        '--schedule',
        type=float,
        default=None,
        metavar='HOURS',
        help='Fetch interval in hours (daemon mode). Examples: 0.25=4x/hr, 0.5=2x/hr (default), 1=1x/hr, 2=every 2 hrs'
    )
    parser.add_argument(
        '--output',
        choices=['csv', 'json', 'parquet', 'both', 'all', 'none'],
        default='parquet',
        help='Output format: csv, json, parquet (default), both (csv+json), all (all formats), or none (display only)'
    )
    
    args = parser.parse_args()
    
    fetcher = AirplaneDataFetcher(timeout=args.timeout)
    
    if args.schedule:
        # Run in scheduler mode
        run_scheduler(
            fetcher,
            interval=args.schedule,
            count=args.count,
            bounds=args.bounds,
            output_format=args.output,
            verbose=args.verbose
        )
    else:
        # Single fetch
        fetch_and_save(
            fetcher,
            count=args.count,
            bounds=args.bounds,
            output_format=args.output,
            verbose=args.verbose
        )


if __name__ == "__main__":
    try:
        logger.info("Starting airplane data fetcher...")
        main()
        logger.info("Fetcher script completed successfully")
    except KeyboardInterrupt:
        logger.warning("Fetcher interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
