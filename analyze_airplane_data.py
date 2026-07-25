"""
Analytics module for airplane data.
Combines all snapshot parquet files into a unified silver dataset.
"""

import polars as pl
from pathlib import Path
from datetime import datetime
import sys
import logging
from logging.handlers import RotatingFileHandler


def setup_logging():
    """
    Set up logging to both console and file.
    Logs are saved to logs/ folder with datetime-based filenames.
    """
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Create logger
    logger = logging.getLogger("airplane_analytics")
    logger.setLevel(logging.DEBUG)
    
    # Log file path with datetime
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = logs_dir / f"analytics_{timestamp}.log"
    
    # Console handler (INFO level - user-friendly)
    # Use UTF-8 encoding to support emoji
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_format)
    try:
        console_handler.stream.reconfigure(encoding='utf-8')
    except AttributeError:
        # Fallback for older Python versions or non-reconfigurable streams
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


def combine_snapshots():
    """
    Combine all parquet snapshots from data/ folder into a single silver dataset.
    Returns a Polars DataFrame.
    """
    data_dir = Path("data")
    
    if not data_dir.exists():
        logger.error("No data/ folder found. Run fetch_airplane_data.py first.")
        return None
    
    # Find all parquet files
    parquet_files = sorted(data_dir.glob("aircraft_data_*.parquet"))
    
    if not parquet_files:
        logger.error("No parquet files found in data/")
        return None
    
    logger.info(f"📦 Found {len(parquet_files)} snapshot files")
    
    # Read and combine all snapshots
    dfs = []
    all_columns = set()
    
    # First pass: collect all columns across all files
    for file in parquet_files:
        try:
            df = pl.read_parquet(file)
            all_columns.update(df.columns)
        except Exception as e:
            logger.warning(f"  ✗ {file.name}: {e}")
    
    # Add snapshot_id to the set of columns we'll standardize
    all_columns.add("snapshot_id")
    
    # Second pass: read files and standardize schemas
    for file in parquet_files:
        try:
            df = pl.read_parquet(file)
            
            # Standardize column names (handle schema drift)
            if "altitude" in df.columns and "baro_altitude" not in df.columns:
                df = df.rename({"altitude": "baro_altitude"})
            
            # Add missing columns with NULL values
            for col in all_columns:
                if col not in df.columns:
                    # Adjust for the rename we just did
                    if col == "baro_altitude" and "altitude" in df.columns:
                        continue
                    # For snapshot_id, we'll add it separately
                    if col == "snapshot_id":
                        continue
                    df = df.with_columns(pl.lit(None).cast(pl.Null).alias(col))
            
            # Add source file timestamp
            df = df.with_columns(
                pl.lit(file.stem.replace("aircraft_data_", "")).alias("snapshot_id")
            )
            
            dfs.append(df)
            logger.debug(f"  ✓ {file.name}")
        except Exception as e:
            logger.error(f"  ✗ {file.name}: {e}")
    
    if not dfs:
        logger.error("No valid parquet files to combine")
        return None
    
    # Sort columns to ensure matching order across all dataframes
    sorted_columns = sorted(all_columns)
    dfs = [df.select(sorted_columns) for df in dfs]
    
    # Concatenate all dataframes (now with matching schemas and order)
    combined = pl.concat(dfs)
    logger.info(f"✅ Combined {len(dfs)} snapshots")
    logger.info(f"   Total records: {len(combined):,}")
    
    return combined


def clean_silver_dataset(df):
    """
    Clean and deduplicate the combined dataset.
    Returns a cleaned Polars DataFrame.
    """
    logger.info("\n🧹 Cleaning dataset...")
    
    # Remove duplicates based on icao24 and time_position within same snapshot
    # This handles cases where the same aircraft appears multiple times
    df_clean = df.unique(subset=["icao24", "time_position", "snapshot_id"])
    
    removed = len(df) - len(df_clean)
    logger.info(f"   Removed duplicates: {removed:,} rows")
    logger.info(f"   Clean records: {len(df_clean):,}")
    logger.debug(f"Duplicate removal stats: {removed} duplicates from {len(df)} total rows")
    
    return df_clean


def analyze_basic_stats(df):
    """Print basic statistics about the dataset."""
    logger.info("\n📊 Dataset Statistics:")
    logger.info(f"   Unique aircraft (ICAO24): {df['icao24'].n_unique():,}")
    logger.info(f"   Unique countries: {df['origin_country'].n_unique():,}")
    logger.info(f"   Time range: {df['last_contact'].min()} → {df['last_contact'].max()}")
    
    # Aircraft on ground vs in air
    on_ground = df.filter(pl.col("on_ground") == True).height
    in_air = df.filter(pl.col("on_ground") == False).height
    logger.info(f"   On ground: {on_ground:,}")
    logger.info(f"   In air: {in_air:,}")
    
    logger.debug(f"Detailed stats - ICAO24 unique: {df['icao24'].n_unique()}, Countries: {df['origin_country'].n_unique()}")
    
    # Top countries
    logger.info("\n🌍 Top 10 Countries:")
    top_countries = (
        df.group_by("origin_country")
        .agg(pl.col("icao24").count().alias("count"))
        .sort("count", descending=True)
        .head(10)
    )
    for row in top_countries.iter_rows(named=True):
        logger.info(f"   {row['origin_country']:20s} {row['count']:6,} aircraft")
        logger.debug(f"Country stats - {row['origin_country']}: {row['count']} aircraft")


def save_silver_dataset(df, output_name=None):
    """
    Save the silver dataset to parquet.
    Returns the file path.
    """
    if output_name is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_name = f"silver_dataset_{timestamp}.parquet"
    
    output_path = Path("data") / output_name
    
    logger.info(f"\n💾 Saving silver dataset to: {output_path}")
    try:
        df.write_parquet(output_path)
        logger.info(f"   ✓ Saved successfully")
        logger.debug(f"Silver dataset saved: {len(df)} rows, {len(df.columns)} columns")
        return output_path
    except Exception as e:
        logger.error(f"   ✗ Error saving silver dataset: {e}")
        return None


def main():
    """Main analysis workflow."""
    logger.info("=" * 60)
    logger.info("✈️  AIRPLANE DATA ANALYTICS")
    logger.info("=" * 60)
    
    # Step 1: Combine all snapshots
    combined_df = combine_snapshots()
    if combined_df is None:
        logger.error("Failed to combine snapshots. Aborting.")
        return
    
    # Step 2: Clean the dataset
    silver_df = clean_silver_dataset(combined_df)
    
    # Step 3: Analyze
    analyze_basic_stats(silver_df)
    
    # Step 4: Save silver dataset
    output_file = save_silver_dataset(silver_df)
    
    logger.info("\n" + "=" * 60)
    if output_file:
        logger.info(f"✅ Analysis complete! Silver dataset saved to: {output_file}")
    else:
        logger.error("❌ Analysis failed during save step.")
    logger.info("=" * 60)
    
    return silver_df


if __name__ == "__main__":
    try:
        logger.info("Starting airplane data analysis...")
        main()
        logger.info("Analysis script completed successfully")
    except KeyboardInterrupt:
        logger.warning("Analysis interrupted by user (Ctrl+C)")
        print("\n⚠️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error during analysis: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
