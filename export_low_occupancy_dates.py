#!/usr/bin/env python3
"""
Export dates with occupancy less than 30% for the next 60 days.
This script generates a CSV file with all dates that have occupancy below 30%.
For onera and wb1 properties only, with fresh data pull at start.
"""

import pandas as pd
import datetime
import sys
import os
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.backend_interface import trigger_rate_generation, trigger_low_occupancy_data_generation
from utils.date_manager import get_operational_range, get_bulk_processing_range
from generate_pl_daily_comprehensive import test_property

def pull_fresh_pl_daily_data(property_keys, force_pull: bool = False):
    """
    Pull fresh pl_daily data for specified properties using generate_pl_daily_comprehensive.py
    
    Args:
        property_keys: List of property keys to pull data for
    
    Returns:
        bool: True if all pulls succeeded, False otherwise
    """
    print("=" * 60)
    print("🔄 PULLING FRESH PL_DAILY DATA")
    print("=" * 60)
    
    # Use a narrower window for this script: today through +90 days
    start_date_obj = datetime.date.today()
    end_date_obj = start_date_obj + datetime.timedelta(days=90)
    start_date = start_date_obj.strftime("%Y-%m-%d")
    end_date = end_date_obj.strftime("%Y-%m-%d")
    
    print(f"📅 Date range for data pull: {start_date} to {end_date}")
    print()
    
    success_count = 0
    for property_key in property_keys:
        pl_daily_path = Path(f"data/{property_key}/pl_daily_{property_key}.csv")
        if not force_pull and pl_daily_path.exists():
            mtime = datetime.datetime.fromtimestamp(pl_daily_path.stat().st_mtime)
            age_hours = (datetime.datetime.now() - mtime).total_seconds() / 3600
            if age_hours < 5:
                print(f"⏭️  Skipping pull for {property_key}: pl_daily is {age_hours:.2f} hours old (<5h)")
                success_count += 1
                continue
        print(f"\n{'='*60}")
        print(f"📥 Pulling fresh data for {property_key}...")
        print(f"{'='*60}")
        try:
            result = test_property(property_key, start_date, end_date)
            if result:
                print(f"✅ Successfully pulled fresh data for {property_key}")
                success_count += 1
            else:
                print(f"❌ Failed to pull data for {property_key}")
        except Exception as e:
            print(f"❌ Error pulling data for {property_key}: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*60}")
    print(f"📊 Data pull summary: {success_count}/{len(property_keys)} properties succeeded")
    print(f"{'='*60}\n")
    
    return success_count == len(property_keys)

def _filter_low_occupancy(generated_df: pd.DataFrame, occupancy_col: str, threshold: float, property_name: str = None) -> pd.DataFrame:
    """
    Return rows below threshold, with property-specific weekday filtering.
    Default: Mon-Wed only (weekday 0, 1, 2)
    Special case for azulik: Sun-Thu only (weekday 6, 0, 1, 2, 3) and from May onwards
    """
    df = generated_df.copy()
    df[occupancy_col] = pd.to_numeric(df[occupancy_col], errors='coerce')
    df['Date'] = pd.to_datetime(df['Date']).dt.normalize()
    
    # Special case for azulik: Sun-Thu (weekday 6, 0, 1, 2, 3) and from May onwards
    if property_name == 'azulik1':
        # Filter for Sunday(6), Monday(0), Tuesday(1), Wednesday(2), Thursday(3)
        weekday_mask = (df['Date'].dt.weekday == 6) | (df['Date'].dt.weekday <= 3)
        df = df[weekday_mask]
        # Filter from May 1st of current year onwards
        today = datetime.date.today()
        may_start = datetime.date(today.year, 5, 1)
        df = df[df['Date'].dt.date >= may_start]
    else:
        # Default: Keep only Monday(0), Tuesday(1), Wednesday(2)
        df = df[df['Date'].dt.weekday <= 2]
    
    return df[df[occupancy_col] < threshold]

def _aggregate_property_dates(low_occ_df: pd.DataFrame, occupancy_col: str) -> pd.DataFrame:
    """
    Collapse listing-level rows into one row per property/date to avoid duplicate date sets.
    """
    if low_occ_df.empty:
        return low_occ_df
    
    grouped = low_occ_df.groupby(['Unit Pool', 'Date'], as_index=False).agg({
        occupancy_col: 'mean',             # Use average occupancy across listings
        'listing_name': 'count',           # Listing count for context
        'Live Rate $': 'mean',
        'Suggested': 'mean'
    })
    return grouped

def _build_date_sets(low_occ_df: pd.DataFrame, occupancy_col: str):
    """
    Group consecutive low-occupancy weekdays into date sets per property.
    
    Returns a list of dicts with keys:
    property, start_date, end_date, days, avg_occ
    """
    date_sets = []
    if low_occ_df.empty:
        return date_sets
    
    for prop_name, prop_df in low_occ_df.groupby('Unit Pool'):
        prop_df = prop_df.sort_values('Date')
        current_set = None
        
        for _, row in prop_df.iterrows():
            date_val = row['Date'].date()
            occ_val = row[occupancy_col]
            
            if current_set is None:
                current_set = {
                    'property': prop_name,
                    'start_date': date_val,
                    'end_date': date_val,
                    'days': 1,
                    'occ_values': [occ_val],
                }
                continue
            
            if date_val == current_set['end_date'] + datetime.timedelta(days=1):
                current_set['end_date'] = date_val
                current_set['days'] += 1
                current_set['occ_values'].append(occ_val)
            else:
                # Close current set
                avg_occ = sum(current_set['occ_values']) / len(current_set['occ_values'])
                current_set['avg_occ'] = avg_occ
                current_set.pop('occ_values', None)
                date_sets.append(current_set)
                # Start new set
                current_set = {
                    'property': prop_name,
                    'start_date': date_val,
                    'end_date': date_val,
                    'days': 1,
                    'occ_values': [occ_val],
                }
        
        if current_set:
            avg_occ = sum(current_set['occ_values']) / len(current_set['occ_values'])
            current_set['avg_occ'] = avg_occ
            current_set.pop('occ_values', None)
            date_sets.append(current_set)
    
    # Sort date sets by start date
    return sorted(date_sets, key=lambda x: (x['start_date'], x['property']))

def export_low_occupancy_dates(
    property_selection=None,
    output_file=None,
    pull_fresh_data=True,
    lookahead_days: int = 60,
    threshold_mode: str = "auto",  # "auto" or "manual"
    manual_threshold: float = None,
    force_fresh_pull: bool = False,
):
    """
    Export dates with occupancy less than 30% for the next 60 days.
    
    Args:
        property_selection: List of property keys to include (default: ['onera', 'wb1'])
        output_file: Output CSV file path (default: auto-generated)
        pull_fresh_data: Whether to pull fresh pl_daily data at the start (default: True)
    
    Returns:
        str: Path to the generated CSV file
    """
    
    # Default to onera and wb1 if no properties specified
    if property_selection is None:
        property_selection = ['onera', 'wb1']
    
    print(f"🏠 Processing properties: {property_selection}")
    
    # Pull fresh pl_daily data at the start if requested
    if pull_fresh_data:
        print("\n🔄 Pulling fresh pl_daily data before analysis...")
        pull_success = pull_fresh_pl_daily_data(property_selection, force_pull=force_fresh_pull)
        if not pull_success:
            print("⚠️  Warning: Some data pulls failed, but continuing with analysis...")
        print()
    
    # Calculate date range: today to lookahead_days out
    today = datetime.date.today()
    end_date = today + datetime.timedelta(days=lookahead_days)
    
    print(f"📅 Exporting low occupancy dates from {today} to {end_date}")
    
    # Generate data for the date range (using simplified function that doesn't require rate tables)
    print("🔄 Loading occupancy data from pl_daily files...")
    generated_df = trigger_low_occupancy_data_generation(property_selection, today, end_date)
    
    if generated_df is None or generated_df.empty:
        print("❌ No data generated. Please check your property selection and date range.")
        return None
    
    print(f"📊 Generated {len(generated_df)} rows of data")
    
    # Ensure we only analyze the requested window (today through +lookahead_days)
    generated_df = generated_df.copy()
    generated_df['Date'] = pd.to_datetime(generated_df['Date']).dt.date
    window_mask = (generated_df['Date'] >= today) & (generated_df['Date'] <= end_date)
    generated_df = generated_df[window_mask]
    if generated_df.empty:
        print(f"ℹ️ No data within the requested {lookahead_days}-day window.")
        return None
    
    # Filter and group low-occupancy weekdays
    occupancy_col = 'Occ% (Curr)'
    
    if occupancy_col not in generated_df.columns:
        print(f"❌ Occupancy column '{occupancy_col}' not found in data")
        print(f"Available columns: {list(generated_df.columns)}")
        return None
    
    # Threshold selection
    if threshold_mode == "manual" and manual_threshold is not None:
        threshold = float(manual_threshold)
        fallback_used = False
    else:
        threshold = 30.0
        fallback_used = False
    
    # Process each property separately to apply property-specific filters
    all_low_occ_dfs = []
    all_prop_date_dfs = []
    
    for prop_name in property_selection:
        prop_df = generated_df[generated_df['Unit Pool'] == prop_name].copy()
        if prop_df.empty:
            continue
        
        # Apply property-specific filtering
        prop_low_occ_df = _filter_low_occupancy(prop_df, occupancy_col, threshold, property_name=prop_name)
        if not prop_low_occ_df.empty:
            all_low_occ_dfs.append(prop_low_occ_df)
            prop_date_df = _aggregate_property_dates(prop_low_occ_df, occupancy_col)
            if not prop_date_df.empty:
                all_prop_date_dfs.append(prop_date_df)
    
    if not all_low_occ_dfs:
        low_occ_df = pd.DataFrame()
        prop_date_df = pd.DataFrame()
    else:
        low_occ_df = pd.concat(all_low_occ_dfs, ignore_index=True)
        prop_date_df = pd.concat(all_prop_date_dfs, ignore_index=True)
    
    date_sets_all = _build_date_sets(prop_date_df, occupancy_col)
    
    if threshold_mode != "manual" and len(date_sets_all) < 5:
        print(f"ℹ️ Found only {len(date_sets_all)} date sets below {threshold}%. Trying 40%...")
        threshold = 40.0
        fallback_used = True
        
        # Re-filter with new threshold
        all_low_occ_dfs = []
        all_prop_date_dfs = []
        for prop_name in property_selection:
            prop_df = generated_df[generated_df['Unit Pool'] == prop_name].copy()
            if prop_df.empty:
                continue
            prop_low_occ_df = _filter_low_occupancy(prop_df, occupancy_col, threshold, property_name=prop_name)
            if not prop_low_occ_df.empty:
                all_low_occ_dfs.append(prop_low_occ_df)
                prop_date_df = _aggregate_property_dates(prop_low_occ_df, occupancy_col)
                if not prop_date_df.empty:
                    all_prop_date_dfs.append(prop_date_df)
        
        if all_low_occ_dfs:
            low_occ_df = pd.concat(all_low_occ_dfs, ignore_index=True)
            prop_date_df = pd.concat(all_prop_date_dfs, ignore_index=True)
        else:
            low_occ_df = pd.DataFrame()
            prop_date_df = pd.DataFrame()
        
        date_sets_all = _build_date_sets(prop_date_df, occupancy_col)
    
    if not date_sets_all:
        weekday_desc = "Mon-Wed" if 'azulik1' not in property_selection else "Sun-Thu (azulik1), Mon-Wed (others)"
        print(f"ℹ️ No qualifying weekday dates found with occupancy less than {threshold}%")
        return None
    
    # Determine weekday description for logging
    weekday_desc = "Mon-Wed"
    if 'azulik1' in property_selection:
        weekday_desc = "Sun-Thu (azulik1), Mon-Wed (others)"
    
    print(f"✅ Found {len(low_occ_df)} rows with occupancy < {threshold}% ({weekday_desc})")
    unique_dates = prop_date_df['Date'].dt.date.unique()
    print(f"📅 Found {len(unique_dates)} unique weekday dates with low occupancy")
    
    # Create summary by date (weekday-only)
    date_summary = prop_date_df.rename(columns={'Unit Pool': 'Property', occupancy_col: 'Occupancy_%', 'listing_name': 'Listings_Count', 'Live Rate $': 'Avg_Live_Rate', 'Suggested': 'Avg_Suggested_Rate'})
    
    date_summary = date_summary[['Date', 'Property', 'Occupancy_%', 'Listings_Count', 'Avg_Live_Rate', 'Avg_Suggested_Rate']].sort_values('Date')
    # Convert dates to plain date objects for cleaner CSV output
    date_summary['Date'] = date_summary['Date'].dt.date
    low_occ_df['Date'] = low_occ_df['Date'].dt.date
    
    # If no output_file is provided, skip CSV exports and print only.
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        detailed_file = output_path.parent / f"detailed_{output_path.name}"
        low_occ_df.to_csv(detailed_file, index=False)
        date_summary.to_csv(output_file, index=False)
        print(f"💾 Detailed data saved to: {detailed_file}")
        print(f"💾 Summary data saved to: {output_file}")
    else:
        print("ℹ️ No output file specified; skipping CSV exports (console only).")
    
    # Print summary to console, separated by property
    weekday_label = "Mon-Wed" if 'azulik1' not in property_selection else "Sun-Thu (azulik1), Mon-Wed (others)"
    print(f"\n📋 SUMMARY OF LOW OCCUPANCY DATES ({weekday_label}) BY PROPERTY:")
    print("=" * 50)
    for prop in sorted(date_summary['Property'].unique()):
        print(f"\n[{prop}]")
        prop_rows = date_summary[date_summary['Property'] == prop]
        for _, row in prop_rows.iterrows():
            print(f"{row['Date']}: {row['Occupancy_%']:.1f}% ({row['Listings_Count']} listings)")
    
    # Print grouped date sets, separated by property (includes single-day spans)
    weekday_label = "Mon-Wed" if 'azulik1' not in property_selection else "Sun-Thu (azulik1), Mon-Wed (others)"
    print(f"\n📅 DATE SETS (grouped consecutive {weekday_label} days) BY PROPERTY:")
    print("=" * 50)
    date_sets_by_prop = {}
    for ds in date_sets_all:
        date_sets_by_prop.setdefault(ds['property'], []).append(ds)
    for prop in sorted(date_sets_by_prop.keys()):
        print(f"\n[{prop}]")
        for idx, ds in enumerate(date_sets_by_prop[prop], start=1):
            start_str = ds['start_date'].strftime("%b %d, %Y")
            end_str = ds['end_date'].strftime("%b %d, %Y")
            avg_occ = ds['avg_occ']
            if ds['start_date'] == ds['end_date']:
                print(f"Set {idx}: {start_str} ({ds['days']} day, avg occ {avg_occ:.1f}%)")
            else:
                print(f"Set {idx}: {start_str} – {end_str} ({ds['days']} days, avg occ {avg_occ:.1f}%)")
    
    return {
        "output_file": str(output_file) if output_file else None,
        "date_summary": date_summary,
        "date_sets": date_sets_all,
        "threshold_used": threshold,
        "fallback_used": fallback_used,
        "low_occ_df": low_occ_df,
    }

def main():
    """Main function for command line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Export dates with low occupancy (configurable).')
    parser.add_argument('--properties', nargs='+', help='Property keys to include (default: onera wb1)')
    parser.add_argument('--output', '-o', help='Output CSV file path (optional)')
    parser.add_argument('--no-fresh-data', action='store_true', help='Skip pulling fresh pl_daily data')
    parser.add_argument('--force-fresh-pull', action='store_true', help='Force pl_daily pull even if recent')
    parser.add_argument('--lookahead-days', type=int, default=60, help='Lookahead window in days (default: 60)')
    parser.add_argument('--threshold-mode', choices=['auto', 'manual'], default='auto', help='Threshold selection mode (auto: 30% with 40% fallback; manual: use --manual-threshold)')
    parser.add_argument('--manual-threshold', type=float, help='Manual occupancy threshold (used when --threshold-mode=manual)')
    
    args = parser.parse_args()
    
    try:
        pull_fresh = not args.no_fresh_data
        result = export_low_occupancy_dates(
            property_selection=args.properties,
            output_file=args.output,
            pull_fresh_data=pull_fresh,
            lookahead_days=args.lookahead_days,
            threshold_mode=args.threshold_mode,
            manual_threshold=args.manual_threshold,
            force_fresh_pull=args.force_fresh_pull,
        )
        output_file = result["output_file"]
        if output_file:
            print(f"\n✅ Export completed successfully!")
            print(f"📁 Files saved:")
            print(f"   - Summary: {output_file}")
            print(f"   - Detailed: detailed_{Path(output_file).name}")
        else:
            print("\n❌ Export failed or no data found")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ Error during export: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()













