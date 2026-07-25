"""
Analytics module for airplane data.
Combines all snapshot parquet files into a unified silver dataset.
"""

import polars as pl
from pathlib import Path
from datetime import datetime
import sys


def combine_snapshots():
    """
    Combine all parquet snapshots from data/ folder into a single silver dataset.
    Returns a Polars DataFrame.
    """
    data_dir = Path("data")
    
    if not data_dir.exists():
        print("❌ No data/ folder found. Run fetch_airplane_data.py first.")
        return None
    
    # Find all parquet files
    parquet_files = sorted(data_dir.glob("aircraft_data_*.parquet"))
    
    if not parquet_files:
        print("❌ No parquet files found in data/")
        return None
    
    print(f"📦 Found {len(parquet_files)} snapshot files")
    
    # Read and combine all snapshots
    dfs = []
    all_columns = set()
    
    # First pass: collect all columns across all files
    for file in parquet_files:
        try:
            df = pl.read_parquet(file)
            all_columns.update(df.columns)
        except Exception as e:
            print(f"  ✗ {file.name}: {e}")
    
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
            print(f"  ✓ {file.name}")
        except Exception as e:
            print(f"  ✗ {file.name}: {e}")
    
    if not dfs:
        print("❌ No valid parquet files to combine")
        return None
    
    # Sort columns to ensure matching order across all dataframes
    sorted_columns = sorted(all_columns)
    dfs = [df.select(sorted_columns) for df in dfs]
    
    # Concatenate all dataframes (now with matching schemas and order)
    combined = pl.concat(dfs)
    print(f"\n✅ Combined {len(dfs)} snapshots")
    print(f"   Total records: {len(combined):,}")
    
    return combined


def clean_silver_dataset(df):
    """
    Clean and deduplicate the combined dataset.
    Returns a cleaned Polars DataFrame.
    """
    print("\n🧹 Cleaning dataset...")
    
    # Remove duplicates based on icao24 and time_position within same snapshot
    # This handles cases where the same aircraft appears multiple times
    df_clean = df.unique(subset=["icao24", "time_position", "snapshot_id"])
    
    print(f"   Removed duplicates: {len(df) - len(df_clean):,} rows")
    print(f"   Clean records: {len(df_clean):,}")
    
    return df_clean


def analyze_basic_stats(df):
    """Print basic statistics about the dataset."""
    print("\n📊 Dataset Statistics:")
    print(f"   Unique aircraft (ICAO24): {df['icao24'].n_unique():,}")
    print(f"   Unique countries: {df['origin_country'].n_unique():,}")
    print(f"   Time range: {df['last_contact'].min()} → {df['last_contact'].max()}")
    
    # Aircraft on ground vs in air
    on_ground = df.filter(pl.col("on_ground") == True).height
    in_air = df.filter(pl.col("on_ground") == False).height
    print(f"   On ground: {on_ground:,}")
    print(f"   In air: {in_air:,}")
    
    # Top countries
    print("\n🌍 Top 10 Countries:")
    top_countries = (
        df.group_by("origin_country")
        .agg(pl.col("icao24").count().alias("count"))
        .sort("count", descending=True)
        .head(10)
    )
    for row in top_countries.iter_rows(named=True):
        print(f"   {row['origin_country']:20s} {row['count']:6,} aircraft")


def save_silver_dataset(df, output_name=None):
    """
    Save the silver dataset to parquet.
    Returns the file path.
    """
    if output_name is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_name = f"silver_dataset_{timestamp}.parquet"
    
    output_path = Path("data") / output_name
    
    print(f"\n💾 Saving silver dataset to: {output_path}")
    df.write_parquet(output_path)
    print(f"   ✓ Saved successfully")
    
    return output_path


def main():
    """Main analysis workflow."""
    print("=" * 60)
    print("✈️  AIRPLANE DATA ANALYTICS")
    print("=" * 60)
    
    # Step 1: Combine all snapshots
    combined_df = combine_snapshots()
    if combined_df is None:
        return
    
    # Step 2: Clean the dataset
    silver_df = clean_silver_dataset(combined_df)
    
    # Step 3: Analyze
    analyze_basic_stats(silver_df)
    
    # Step 4: Save silver dataset
    output_file = save_silver_dataset(silver_df)
    
    print("\n" + "=" * 60)
    print(f"✅ Analysis complete! Silver dataset saved to: {output_file}")
    print("=" * 60)
    
    return silver_df


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
