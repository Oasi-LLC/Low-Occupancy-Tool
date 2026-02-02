# src/pricing_engine/dataloader.py

import pandas as pd
from pathlib import Path
import datetime
from typing import Dict, Set, Tuple, Any, Optional

# Assuming utils.py is in the same directory or Python path is set correctly
from . import utils # Use relative import within the package

def _parse_mixed_date(date_val: Any) -> pd.Timestamp:
    """Attempts to parse a date string in M/D/YY format first,
       then falls back to parsing as an Excel serial number if the first fails.
    """
    if pd.isna(date_val):
        return pd.NaT
    try:
        # Attempt standard M/D/YY format first
        # Use errors='raise' to trigger the except block if format is wrong
        return pd.to_datetime(date_val, format='%m/%d/%y', errors='raise')
    except (ValueError, TypeError):
        try:
            # If standard parse fails, attempt Excel serial number format
            # Convert to numeric first, coercing errors (like non-numeric strings)
            numeric_val = pd.to_numeric(date_val, errors='coerce')
            if pd.isna(numeric_val):
                return pd.NaT # Value wasn't a valid number
            # Origin for Excel serial dates (adjust if using Mac 1904 base)
            return pd.to_datetime(numeric_val, unit='D', origin='1899-12-30')
        except (ValueError, TypeError):
            # If both attempts fail, return NaT
            return pd.NaT

def load_and_preprocess_data(property_name: str, property_config: dict) -> Tuple[pd.DataFrame, Dict[str, str], Set[Tuple[str, str]], Dict[str, float], Optional[Dict[str, float]]]:
    """
    Loads and preprocesses all necessary data for a given property.

    Args:
        property_name: The identifier of the property (e.g., 'onera'),
                       corresponding to the data subdirectory name.
        property_config: The configuration dictionary for this specific property
                         loaded from properties.yaml.

    Returns:
        A tuple containing:
        - rate_table_df: DataFrame of the property's rate table.
        - date_tier_map: Dictionary mapping 'YYYY-MM-DD' -> tier_group string.
        - booked_blocked_set: Set of tuples ('listing_id', 'YYYY-MM-DD')
                              for dates that are booked or blocked.
        - occupancy_map: Dictionary mapping 'YYYY-MM-DD' -> occupancy percentage (0-100).
        - event_multiplier_map: Optional dictionary mapping 'YYYY-MM-DD' -> event multiplier (float). Returns None if file not found.

    Raises:
        FileNotFoundError: If any required CSV file is missing.
        KeyError: If expected columns are missing in the CSV files.
        ValueError: If critical data cannot be processed (e.g., date parsing).
    """
    print(f"--- Loading data for property: {property_name} ---")
    base_path = Path("data") / property_name
    
    # Calculate total units for occupancy denominator
    # First try to use total_units field if available
    total_units_for_property = property_config.get('total_units')
    
    # If not available, sum units from each listing
    if total_units_for_property is None:
        total_units_for_property = sum(
            listing.get('units', 1) for listing in property_config.get('listings', [])
        )
    
    # Last resort fallback: Use listing count if no unit info available
    if not total_units_for_property:
        total_units_for_property = len(property_config.get('listings', []))
    
    # Still need total_listings_for_property for other purposes
    total_listings_for_property = len(property_config.get('listings', []))
    
    if total_listings_for_property == 0:
        raise ValueError(f"No listings found in configuration for property '{property_name}'. Cannot calculate occupancy.")

    # Create a mapping from listing ID to listing name
    listing_id_map = {
        str(listing['id']): listing['name']
        for listing in property_config.get('listings', [])
        if 'id' in listing and 'name' in listing # Basic validation
    }
    if not listing_id_map:
        print(f"Warning: Could not create listing ID to name map for property '{property_name}'. Check configuration.")


    # --- Load Rate Table ---
    rate_table_path = base_path / f"rate_table_{property_name}.csv"
    try:
        rate_table_df = pd.read_csv(rate_table_path)
        # Basic validation (add more checks as needed)
        required_rate_cols = ['tier_group', 'day_group', 'booking_window', 'Occupancy Band', 'occupancy_min_pct', 'occupancy_max_pct']
        # Add expected rate group columns based on config
        for rate_col in property_config.get('rate_group_mapping', {}).keys():
             required_rate_cols.append(rate_col) # Assumes column names match keys directly

        if not all(col in rate_table_df.columns for col in required_rate_cols):
             raise KeyError(f"Rate table missing one or more required columns: {required_rate_cols}")

        # Clean rate columns by removing dollar signs and extra spaces
        for rate_col in property_config.get('rate_group_mapping', {}).keys():
            if rate_col in rate_table_df:
                # Convert to string type FIRST, handling potential non-string data gracefully
                rate_table_df[rate_col] = rate_table_df[rate_col].astype(str)
                # Now apply string operations
                rate_table_df[rate_col] = rate_table_df[rate_col].str.replace('$', '', regex=False).str.strip()
                # Optional: Convert back to numeric if needed later, coercing errors
                # rate_table_df[rate_col] = pd.to_numeric(rate_table_df[rate_col], errors='coerce')
            else:
                print(f"Warning: Rate column '{rate_col}' defined in properties.yaml but not found in rate table {rate_table_path}")

        print(f"Loaded Rate Table: {rate_table_path}")
    except FileNotFoundError:
        raise FileNotFoundError(f"Rate table file not found: {rate_table_path}")
    except Exception as e:
        raise ValueError(f"Error loading or validating rate table {rate_table_path}: {e}")


    # --- Load Date Tiers ---
    dates_tiers_path = base_path / f"dates_tiers_{property_name}.csv"
    date_tier_map: Dict[str, str] = {}
    try:
        # UPDATED: Hardcode for onera comma separator and column names
        dates_tiers_df = pd.read_csv(
            dates_tiers_path,
            sep=',',              # onera uses comma
            usecols=['Date', 'Tier'], # Use column names matching onera
            parse_dates=['Date'],   # Parse the 'Date' column
            header=0             # Assumes first row IS a header
        )
        # Rename columns for clarity after loading
        # Ensure internal code uses consistent names ('date', 'tier_group')
        dates_tiers_df.columns = ['date', 'tier_group']

        if not pd.api.types.is_datetime64_any_dtype(dates_tiers_df['date']):
             raise ValueError("Could not parse 'date' column as datetime.")

        for _, row in dates_tiers_df.iterrows():
             # Ensure date is valid and format it; handle potential NaT dates
             if pd.notna(row['date']) and pd.notna(row['tier_group']):
                  date_str = utils.format_date(row['date'].date())
                  date_tier_map[date_str] = str(row['tier_group']).strip() # Ensure tier is string
        print(f"Loaded Date Tiers: {dates_tiers_path}, {len(date_tier_map)} entries processed.")
    except FileNotFoundError:
        raise FileNotFoundError(f"Dates tiers file not found: {dates_tiers_path}")
    except Exception as e:
        raise ValueError(f"Error loading or processing date tiers {dates_tiers_path}: {e}")


    # --- Load PL Daily (for Booked/Blocked Status) ---
    pl_daily_path = base_path / f"pl_daily_{property_name}.csv"
    booked_blocked_set: Set[Tuple[str, str]] = set()
    try:
        # UPDATED: Use new PL daily format columns
        pl_df = pd.read_csv(
            pl_daily_path,
            usecols=['Date', 'Listing ID', 'No. Booked', 'No. Blocked', 'Vacant Units'], # Use new format columns
            dtype={'Listing ID': str} # Ensure Listing ID is read as string
        )

        # Convert numeric columns, coercing errors to NaN
        pl_df['No. Booked'] = pd.to_numeric(pl_df['No. Booked'], errors='coerce').fillna(0)
        pl_df['No. Blocked'] = pd.to_numeric(pl_df['No. Blocked'], errors='coerce').fillna(0)
        pl_df['Vacant Units'] = pd.to_numeric(pl_df['Vacant Units'], errors='coerce').fillna(0)

        # Parse the date format - try standard date parsing first
        pl_df['Date'] = pd.to_datetime(pl_df['Date'], errors='coerce')

        # Use 'Date' column for validation
        if not pd.api.types.is_datetime64_any_dtype(pl_df['Date']):
             raise ValueError("Could not parse 'Date' column as datetime.")

        # Filter for relevant rows
        # UPDATED: Only consider listings as "booked" when they have zero vacant units
        # This ensures only completely booked listings (not partially booked) are flagged
        relevant_pl = pl_df[ pl_df['Vacant Units'] == 0 ].copy()

        # Process into the set
        for _, row in relevant_pl.iterrows():
            # Use 'Date' column for date processing
            if pd.notna(row['Date']) and pd.notna(row['Listing ID']):
                date_str = utils.format_date(row['Date'].date())
                listing_id = str(row['Listing ID']).strip()
                # Directly add the ID to the set
                booked_blocked_set.add((listing_id, date_str))

        print(f"Loaded PL Daily: {pl_daily_path}, {len(booked_blocked_set)} fully booked entries processed.")

        # --- Calculate occupancy from PL Daily data ---
        occupancy_map = {}
        try:
            # Group by date and sum vacant units
            pl_df_with_date = pl_df.copy()
            pl_df_with_date['Date_str'] = pl_df_with_date['Date'].dt.date.apply(utils.format_date)
            
            # Calculate vacancy by date
            vacancy_by_date = pl_df_with_date.groupby('Date_str')['Vacant Units'].sum().to_dict()
            
            # Calculate occupied units and occupancy percentage for each date
            for date_str, vacant_units in vacancy_by_date.items():
                # Number of occupied units = total units - vacant units
                occupied_units = total_units_for_property - vacant_units
                # Calculate occupancy percentage
                occupancy_pct = (occupied_units / total_units_for_property) * 100
                # Store in occupancy map
                occupancy_map[date_str] = occupancy_pct
                
                # Debug logging for current operational date range
                from utils.date_manager import get_operational_range
                start_date, end_date = get_operational_range()
                current_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                if start_date <= current_date <= end_date:
                    print(f"DEBUG: Date {date_str} - Total units: {total_units_for_property}, Vacant: {vacant_units}, Occupied: {occupied_units}, Occupancy: {occupancy_pct:.2f}%")
                
            print(f"Calculated occupancy from vacant units for {len(occupancy_map)} dates.")
        except Exception as e:
            print(f"Warning: Error calculating occupancy from PL Daily: {e}. Will try using resdata instead.")
    except FileNotFoundError:
        raise FileNotFoundError(f"PL Daily file not found: {pl_daily_path}")
    except KeyError as e:
         raise KeyError(f"Missing expected column in {pl_daily_path}: {e}. Check usecols.")
    except Exception as e:
        raise ValueError(f"Error loading or processing PL Daily {pl_daily_path}: {e}")


    # --- Load Event Modifiers (Optional) ---
    events_path = base_path / f"events_mod_{property_name}.csv"
    # Initialize here, before the try block, ensures it's always defined
    event_multiplier_map: Optional[Dict[str, float]] = None 
    try:
        if events_path.exists():
            events_df = pd.read_csv(
                events_path,
                usecols=['Date', 'Multiplier'], # Expect these columns
                parse_dates=['Date']
            )

            # Validate columns and data types
            if not pd.api.types.is_datetime64_any_dtype(events_df['Date']):
                raise ValueError("Could not parse 'Date' column as datetime in events file.")
            if not pd.api.types.is_numeric_dtype(events_df['Multiplier']):
                 # Attempt conversion, coercing errors
                 events_df['Multiplier'] = pd.to_numeric(events_df['Multiplier'], errors='coerce')
                 if events_df['Multiplier'].isnull().any():
                     print(f"Warning: Non-numeric Multiplier values found in {events_path}. These rows will be ignored.")
                     events_df = events_df.dropna(subset=['Multiplier']) # Drop rows that failed conversion

            # Create the dictionary map
            event_multiplier_map = {} # Initialize the dictionary ONLY if file exists and is valid so far
            for _, row in events_df.iterrows():
                 if pd.notna(row['Date']) and pd.notna(row['Multiplier']):
                     date_obj = row['Date'].date() # Get date object
                     date_str = utils.format_date(date_obj) # Format date
                     multiplier = float(row['Multiplier']) # Ensure float
                     event_multiplier_map[date_str] = multiplier
            print(f"Loaded Event Modifiers: {events_path}, {len(event_multiplier_map)} entries processed.")
        else:
            print(f"Event modifier file not found (optional): {events_path}")
            # event_multiplier_map remains None as initialized

    except FileNotFoundError: # Should technically be caught by exists(), but for safety
        print(f"Event modifier file not found (optional): {events_path}")
        event_multiplier_map = None # Explicitly None
    except KeyError as e:
         print(f"Warning: Missing expected column in {events_path}: {e}. Skipping event modifiers.")
         event_multiplier_map = None # Skip if columns missing
    except Exception as e:
        print(f"Warning: Error loading or processing Event Modifiers {events_path}: {e}. Skipping event modifiers.")
        event_multiplier_map = None # Skip on other errors

    print(f"--- Data loading complete for {property_name} ---")
    return rate_table_df, date_tier_map, booked_blocked_set, occupancy_map, event_multiplier_map
