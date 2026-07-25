# aircraft-analytics-pipeline

Fetch real-time airplane data using the **OpenSky Network API** (free tier, no API key required) and perform advanced analytics on the dataset. Captures all 18 fields available from the API including position, altitude, velocity, aircraft category, and sensor information. Built for data collection, analysis, and visualization workflows.

## Setup

### 1. Create and activate a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies:
```bash
pip install -r requirements.txt
```

### 3. Deactivate virtual environment (when done):
```bash
deactivate
```

## Usage

### Basic usage - fetch all currently visible aircraft (saves to Parquet by default):
```bash
python fetch_airplane_data.py
```

### Fetch first 10 aircraft:
```bash
python fetch_airplane_data.py --count 10
```

### Fetch to CSV instead:
```bash
python fetch_airplane_data.py --output csv
```

### **Fetch twice per hour (daemon mode, default - every 30 minutes):**
```bash
python fetch_airplane_data.py --schedule 0.5
```

### Fetch every hour (daemon mode):
```bash
python fetch_airplane_data.py --schedule 1
```

### Fetch every 2 hours:
```bash
python fetch_airplane_data.py --schedule 2
```

### Fetch 4 times per hour (every 15 minutes):
```bash
python fetch_airplane_data.py --schedule 0.25
```

### Fetch twice per hour and save to CSV:
```bash
python fetch_airplane_data.py --schedule 0.5 --output csv
```

### Fetch twice per hour and save to JSON:
```bash
python fetch_airplane_data.py --schedule 0.5 --output json
```

### Fetch twice per hour and save to both CSV and JSON:
```bash
python fetch_airplane_data.py --schedule 0.5 --output both
```

### Fetch with detailed info:
```bash
python fetch_airplane_data.py --verbose
```

### Fetch aircraft from specific region (bounds):
```bash
python fetch_airplane_data.py --bounds 40.0 45.0 -75.0 -70.0
```
(Format: min_latitude max_latitude min_longitude max_longitude)

### Increase timeout (useful for large queries):
```bash
python fetch_airplane_data.py --count 100 --timeout 20
```

## Output Options

Save fetched data in different formats to the `data/` folder:

- `--output parquet` (default) - Save to **data/aircraft_data_YYYY-MM-DD_HHMMSS.parquet** (new dated file each fetch, efficient columnar format)
- `--output csv` - Save to **data/aircraft_data.csv** (appends new rows each fetch)
- `--output json` - Save to **data/aircraft_data.json** (overwrites with latest fetch)
- `--output both` - Save to both CSV and JSON
- `--output all` - Save to CSV, JSON, and Parquet
- `--output none` - Display only, don't save

### Parquet Format (Polars) - Default

Parquet files are automatically created with datetime stamps. Default fetches **twice per hour (every 30 minutes)**:

```
data/
├── aircraft_data_2026-07-25_143000.parquet
├── aircraft_data_2026-07-25_143030.parquet
├── aircraft_data_2026-07-25_144000.parquet
├── aircraft_data_2026-07-25_144030.parquet
└── ...
```

**Advantages:**
- 🚀 Faster queries than CSV
- 💾 Significantly smaller file size (compression built-in)
- 📊 Better for data analysis (Pandas/Polars compatible)
- ⚡ Efficient for large datasets
- 📅 Each file is timestamped for easy tracking

**Read parquet file with Polars:**
```python
import polars as pl
df = pl.read_parquet('data/aircraft_data_2026-07-25_143045.parquet')
print(df)

# Read and combine all parquet files
import glob
dfs = [pl.read_parquet(f) for f in glob.glob('data/aircraft_data_*.parquet')]
combined_df = pl.concat(dfs)
print(combined_df)
```

**Read parquet file with Pandas:**
```python
import pandas as pd
df = pd.read_parquet('data/aircraft_data_2026-07-25_143045.parquet')
print(df)
```

## Data Fields

Each aircraft record includes all 18 fields from the OpenSky Network API:

### Core Fields
- **icao24**: Unique ICAO 24-bit address (hex string) - aircraft identifier
- **callsign**: Flight callsign/number (8 chars, may be null)
- **origin_country**: Country name inferred from ICAO address
- **latitude**: WGS-84 latitude in decimal degrees (or null)
- **longitude**: WGS-84 longitude in decimal degrees (or null)
- **on_ground**: Boolean - whether position is from surface report

### Altitude & Speed
- **baro_altitude**: Barometric altitude in meters (or null)
- **geo_altitude**: Geometric altitude in meters (or null)
- **velocity**: Velocity over ground in m/s (or null)
- **vertical_rate**: Vertical rate in m/s (positive=climbing, negative=descending, or null)
- **true_track**: True track in degrees clockwise from north (or null)

### Time & Update Info
- **time_position**: Unix timestamp for last position update (or null if none in past 15s)
- **last_contact**: Unix timestamp for last general update
- **sensors**: Array of receiver IDs that contributed to this state vector (or null)

### Additional Info
- **squawk**: Transponder code/Squawk (or null)
- **spi**: Boolean - whether flight status indicates special purpose indicator
- **position_source**: Origin of position data:
  - 0 = ADS-B
  - 1 = ASTERIX
  - 2 = MLAT
  - 3 = FLARM
- **category**: Aircraft category:
  - 0 = No information
  - 1 = No ADS-B Category info
  - 2 = Light (< 15500 lbs)
  - 3 = Small (15500-75000 lbs)
  - 4 = Large (75000-300000 lbs)
  - 5 = High Vortex Large (B-757)
  - 6 = Heavy (> 300000 lbs)
  - 7 = High Performance (> 5g acceleration)
  - 8 = Rotorcraft
  - 9 = Glider/sailplane
  - 10 = Lighter-than-air
  - 11 = Parachutist/skydiver
  - 12 = Ultralight/hang-glider
  - 14 = Unmanned Aerial Vehicle
  - 16 = Emergency Vehicle
  - 17 = Service Vehicle
  - 18 = Point Obstacle (balloons)
  - 19 = Cluster Obstacle
  - 20 = Line Obstacle

## API Information

- **Source**: OpenSky Network (https://opensky-network.org/)
- **Rate Limit**: ~4000 requests/hour (free tier)
- **Cost**: Free (no API key required)
- **Coverage**: Global real-time aircraft tracking

## Example Output

```
✈️  BA127     | United Kingdom         | Pos: (51.45, -0.12) | Alt: 10668m  | Speed: 250.5m/s    | In Flight
✈️  DL45      | United States          | Pos: (40.64, -73.98) | Alt: 3048m   | Speed: 180.2m/s    | In Flight
✈️  LH501     | Germany                | Pos: (52.35, 13.42) | Alt: 11887m  | Speed: 235.0m/s    | In Flight
```

## Scheduler (Daemon Mode)

The `--schedule` option runs the script continuously, fetching data at regular intervals and saving to `data/` folder. Default is **twice per hour (every 30 minutes)**:

```bash
# Fetch twice per hour (default - every 30 minutes to Parquet)
python fetch_airplane_data.py --schedule 0.5

# Fetch 4 times per hour (every 15 minutes)
python fetch_airplane_data.py --schedule 0.25

# Fetch every hour to Parquet
python fetch_airplane_data.py --schedule 1

# Fetch every 3 hours to Parquet
python fetch_airplane_data.py --schedule 3

# Fetch twice per hour, save to all formats
python fetch_airplane_data.py --schedule 0.5 --output all

# Fetch twice per hour with custom region
python fetch_airplane_data.py --schedule 0.5 --bounds 40.0 45.0 -75.0 -70.0 --output parquet
```

- Press **Ctrl+C** to stop the scheduler
- Data is saved to `data/` folder
- Each parquet file has a datetime stamp (e.g., `aircraft_data_2026-07-25_143045.parquet`)
- CSV file appends new rows (historical data preserved)
- JSON file is overwritten with latest data
- Process runs in the foreground; use `nohup` or task scheduler to run in background

### Running in Background (Windows)

Create a batch file `run_scheduler.bat`:
```batch
@echo off
python fetch_airplane_data.py --schedule 0.5 --output parquet
pause
```

Then schedule it with Windows Task Scheduler.

### Running in Background (Linux/Mac)

```bash
nohup python fetch_airplane_data.py --schedule 0.5 --output parquet &
```

## Crontab Setup (Linux/Mac)

Use **crontab** to automatically run the script on a schedule without keeping it running in the foreground.

### View current crontab:
```bash
crontab -l
```

### Edit crontab:
```bash
crontab -e
```

### Add entries to crontab:

**Every 30 minutes (twice per hour):**
```crontab
*/30 * * * * cd /path/to/airplane && /usr/bin/python3 fetch_airplane_data.py --output parquet
```

**Every 15 minutes (4 times per hour):**
```crontab
*/15 * * * * cd /path/to/airplane && /usr/bin/python3 fetch_airplane_data.py --output parquet
```

**Every hour at the top of the hour:**
```crontab
0 * * * * cd /path/to/airplane && /usr/bin/python3 fetch_airplane_data.py --output parquet
```

**Every 2 hours:**
```crontab
0 */2 * * * cd /path/to/airplane && /usr/bin/python3 fetch_airplane_data.py --output parquet
```

**Every day at 8 AM:**
```crontab
0 8 * * * cd /path/to/airplane && /usr/bin/python3 fetch_airplane_data.py --output parquet
```

**Every 6 hours to Parquet:**
```crontab
0 0,6,12,18 * * * cd /path/to/airplane && /usr/bin/python3 fetch_airplane_data.py --output parquet
```

**Every hour saving all formats (CSV + JSON + Parquet):**
```crontab
0 * * * * cd /path/to/airplane && /usr/bin/python3 fetch_airplane_data.py --output all >> airplane.log 2>&1
```

### Crontab Format

```
┌───────────── minute (0 - 59)
│ ┌───────────── hour (0 - 23)
│ │ ┌───────────── day of month (1 - 31)
│ │ │ ┌───────────── month (1 - 12)
│ │ │ │ ┌───────────── day of week (0 - 6) (Sunday to Saturday)
│ │ │ │ │
│ │ │ │ │
* * * * * command to run
```

### Examples:

| Schedule | Crontab |
|----------|---------|
| Every hour | `0 * * * *` |
| Every 30 minutes | `*/30 * * * *` |
| Every 2 hours | `0 */2 * * *` |
| Every 6 hours | `0 0,6,12,18 * * *` |
| Every day at 9 AM | `0 9 * * *` |
| Every Monday at 8 AM | `0 8 * * 1` |
| Every 1st of month | `0 0 1 * *` |
| Every 15 minutes | `*/15 * * * *` |

### Finding Python Path

```bash
which python3
# Output: /usr/bin/python3
```

### Tips

- Always use **full paths** in crontab (not `python3`, use `/usr/bin/python3`)
- Always use **absolute paths** to your project directory
- Use `cd /path/to/project &&` before running the script
- Redirect output to log file:
  ```crontab
  0 * * * * cd /path/to/airplane && /usr/bin/python3 fetch_airplane_data.py --output csv >> airplane.log 2>&1
  ```

- View logs:
  ```bash
  tail -f airplane.log
  ```

- Test crontab entry before saving by running command manually:
  ```bash
  cd /path/to/airplane && /usr/bin/python3 fetch_airplane_data.py --output csv
  ```

## Notes

- First request may take 5-10 seconds as it connects to the API
- Free tier has rate limits (~4000 requests/hour); default is 2 requests per hour (well within limit)
- Altitude may be `None` for some aircraft
- Data updates every ~10-15 seconds on the API side
- All files are saved to `data/` folder (created automatically)
- Parquet files are created with datetime stamps for easy tracking (default: twice per hour)
- CSV file grows with each fetch; combine with other CSVs for historical analysis
- Parquet format is space-efficient compared to CSV (built-in compression)
- JSON file is replaced each fetch; use it for latest snapshot only
