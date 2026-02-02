import streamlit as st
import pandas as pd
import datetime
import yaml
from pathlib import Path
import traceback
import uuid # For generating unique IDs
from typing import Optional, Dict # Import Dict
import logging # <-- Add logging import
from rates.logging_setup import setup_logging, log_price_update

# --- Import necessary functions from the pricing engine --- 
# Assuming PYTHONPATH is set correctly or the structure allows these imports
# Adjust relative paths if needed based on execution context
from src.pricing_engine import dataloader, calculator, utils

CONFIG_PATH = Path("config/properties.yaml")
OUTPUT_DIR = Path("data/outputs")
LOG_DIR = Path("logs") # <-- Define log directory
LOG_DIR.mkdir(parents=True, exist_ok=True) # <-- Ensure log directory exists

# --- Cached Functions --- 

@st.cache_data(ttl=3600) # Cache for 1 hour
def load_properties_config():
    """Loads the properties configuration from YAML."""
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
        if "properties" not in config or not isinstance(config["properties"], dict):
            st.error("Invalid properties.yaml structure: Missing top-level 'properties' key or it's not a dictionary.")
            return None
        print(f"Loaded properties config from {CONFIG_PATH}")
        return config["properties"]
    except FileNotFoundError:
        st.error(f"Configuration file not found: {CONFIG_PATH}")
        return None
    except yaml.YAMLError as e:
        st.error(f"Error parsing YAML configuration file {CONFIG_PATH}: {e}")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred loading configuration: {e}")
        return None

@st.cache_data
def get_available_properties() -> list:
    """Returns a list of available property keys from the config."""
    properties_config = load_properties_config()
    if properties_config:
        return list(properties_config.keys())
    return []

@st.cache_data
def get_property_display_names() -> dict:
    """Returns a dict mapping property keys to display names."""
    properties_config = load_properties_config()
    if properties_config:
        return {k: v.get('name', k) for k, v in properties_config.items()}
    return {}

# Caching get_rate_details might be less useful if it just formats passed data,
# but can be added if it performs expensive lookups later.
# @st.cache_data
def get_rate_details(rate_data_row: pd.Series) -> dict:
    """Extracts and formats details for a specific rate from its data row."""
    # This function now expects the actual data row (Pandas Series) as input
    # Modification in app.py needed: Pass the row instead of just the ID.
    if rate_data_row is None or rate_data_row.empty:
        return {'Unit Pool': 'Unknown', 'Date': datetime.date.today(), 'Suggested Price': 0.0, 'Current Live Rate': 0.0, 'Baseline': 0.0, 'Flag Reason': '', 'Occupancy %': {'Current': 0.0, 'Historical': 0.0}, 'Historical Pace': 0.0, 'lookup_error': ''}

    # Extract details - use .get() for robustness against missing columns
    details = {
        'Unit Pool': rate_data_row.get('Unit Pool', 'N/A'),
        'Date': pd.to_datetime(rate_data_row.get('Date')).date() if pd.notna(rate_data_row.get('Date')) else datetime.date.today(),
        'Suggested Price': float(rate_data_row.get('Suggested', 0.0)) if pd.notna(rate_data_row.get('Suggested')) else 0.0,
        'Current Live Rate': float(rate_data_row.get('Current Live Rate', 0.0)) if pd.notna(rate_data_row.get('Current Live Rate')) else 0.0, # Assuming this column exists or is added
        'Baseline': float(rate_data_row.get('Baseline', 0.0)) if pd.notna(rate_data_row.get('Baseline')) else 0.0,
        'Flag Reason': rate_data_row.get('Flag', ''), # Use Flag column for reason for now
        'Occupancy %': {
            'Current': float(rate_data_row.get('Occ% (Curr)', 0.0)) if pd.notna(rate_data_row.get('Occ% (Curr)')) else 0.0,
            'Historical': float(rate_data_row.get('Occ% (Hist)', 0.0)) if pd.notna(rate_data_row.get('Occ% (Hist)')) else 0.0
        },
        'Historical Pace': float(rate_data_row.get('Pace', 0.0)) if pd.notna(rate_data_row.get('Pace')) else 0.0,
        'lookup_error': rate_data_row.get('lookup_error', '') # Add the lookup error message
    }
    return details


# --- Core Logic Functions (No Caching - need fresh results) ---

def trigger_rate_generation(property_selection: list, start_date: datetime.date, end_date: datetime.date) -> Optional[pd.DataFrame]:
    """Orchestrates loading data and calculating rates for selected properties/dates."""

    # --- Setup Logging for this run ---
    run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = LOG_DIR / f"rate_generation_{run_timestamp}.log"
    # Configure logging (basic setup, customize format/level as needed)
    # Remove existing handlers to avoid duplicate logs if function is called multiple times
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename),
            # logging.StreamHandler() # Optionally add stream handler for console output too
        ]
    )
    logging.info(f"Starting rate generation run. Log file: {log_filename}")
    logging.info(f"Properties selected: {property_selection}")
    logging.info(f"Display date range: {start_date} to {end_date}")
    logging.info(f"Note: Using full 2-year dataset for occupancy calculations")
    # --- End Logging Setup ---

    all_properties_config = load_properties_config()
    if not all_properties_config:
        logging.error("Failed to load properties configuration.") # <-- Log error
        return None

    all_results = []
    full_dataset_results = []  # Store full dataset for calculations
    today = datetime.date.today()
    logging.info(f"Reference date (today): {today}") # <-- Log info

    for prop_name in property_selection:
        logging.info(f"Processing property: {prop_name}") # <-- Log info
        if prop_name not in all_properties_config:
            st.warning(f"Configuration not found for property: {prop_name}. Skipping.")
            logging.warning(f"Configuration not found for property: {prop_name}. Skipping.") # <-- Log warning
            continue

        prop_config = all_properties_config[prop_name]
        listing_ids_for_property = [str(listing['id']) for listing in prop_config.get('listings', []) if 'id' in listing]

        if not listing_ids_for_property:
            st.warning(f"No listing IDs found in config for property: {prop_name}. Skipping.")
            logging.warning(f"No listing IDs found in config for property: {prop_name}. Skipping.") # <-- Log warning
            continue

        try:
            logging.info(f"--- Loading data for {prop_name} ---") # <-- Log info
            # Load event multipliers along with other data
            rate_table_df, date_tier_map, booked_blocked_set, occupancy_map, event_multiplier_map = dataloader.load_and_preprocess_data(prop_name, prop_config)
            logging.info(f"--- Data loaded for {prop_name}. Calculating rates... ---") # <-- Log info

            # Use full date range for calculations but only return user's selected range
            from utils.date_manager import get_full_calculation_range
            full_start_date, full_end_date = get_full_calculation_range()
            full_date_range = pd.date_range(full_start_date, full_end_date, freq='D')
            
            # User's selected date range for display
            user_date_range = pd.date_range(start_date, end_date, freq='D')
            
            # Load pl_daily data once per property for efficiency
            pl_daily_path = f"data/{prop_name}/pl_daily_{prop_name}.csv"
            pl_df = None
            try:
                pl_df = pd.read_csv(pl_daily_path)
                # Fix date matching by extracting just the date part
                pl_df['Date_clean'] = pl_df['Date'].str.split('T').str[0]
            except Exception as e:
                logging.error(f"Error loading pl_daily data for {prop_name}: {e}")
            
            # Load live rates data (including min_stay and currency)
            live_rates_map = {}
            live_rates_filename = f"{prop_name}_nightly_pulled_overrides.csv"
            live_rates_path = Path("data") / prop_name / live_rates_filename
            if live_rates_path.exists():
                try:
                    # Try to load with currency if available
                    live_rates_df = pd.read_csv(live_rates_path)
                    required_cols = ['listing_id', 'date', 'price', 'min_stay']
                    has_currency = 'currency' in live_rates_df.columns
                    
                    if has_currency:
                        live_rates_df = live_rates_df[required_cols + ['currency']]
                    else:
                        live_rates_df = live_rates_df[required_cols]
                    
                    live_rates_df = live_rates_df.astype({
                        'listing_id': str, 
                        'date': str, 
                        'price': float, 
                        'min_stay': 'Int64'
                    })
                    
                    # Create mapping key: listing_id_date -> (price, min_stay, currency)
                    for _, row in live_rates_df.iterrows():
                        map_key = f"{row['listing_id']}_{row['date']}"
                        live_rates_map[map_key] = {
                            'price': row['price'],
                            'min_stay': row['min_stay'] if pd.notna(row['min_stay']) else 1,
                            'currency': row.get('currency', None) if has_currency else None
                        }
                    logging.info(f"Loaded {len(live_rates_map)} live rates from {live_rates_path}")
                except Exception as e:
                    logging.warning(f"Error loading live rates from {live_rates_path}: {e}")
            else:
                logging.warning(f"Live rates file not found: {live_rates_path}")
            
            # Process all dates for accurate occupancy calculations
            for current_date in full_date_range:
                current_date_obj = current_date.date()
                current_date_str = utils.format_date(current_date_obj)
                day_group = utils.get_day_group(current_date_obj)
                booking_window = utils.get_booking_window_label(current_date_obj, today, prop_config.get('booking_window_definitions', []))
                tier_group = date_tier_map.get(current_date_str)
                occupancy_pct = occupancy_map.get(current_date_str, 0.0)
                # Assign urgency_band only if all urgency_configuration conditions are met
                urgency_band = ""
                urgency_config = prop_config.get('urgency_configuration', {})
                tier_groups = urgency_config.get('tier_groups', [])
                urgency_window_label = urgency_config.get('booking_window_label', "")
                max_occupancy_pct = urgency_config.get('max_occupancy_pct', 100)
                # Extract just the label part, e.g., "W1" from "0-9 Days (W1)"
                current_window_label = booking_window.split('(')[-1].strip(')')
                if (
                    tier_group in tier_groups and
                    current_window_label == urgency_window_label and
                    occupancy_pct <= max_occupancy_pct
                ):
                    urgency_band = utils.get_urgency_band(current_date_obj, today, prop_config.get('urgency_band_definitions', []))

                if not tier_group:
                    # st.warning(f"Tier group not found for {current_date_str} in property {prop_name}. Skipping rate calculation for this date.")
                    logging.warning(f"Property {prop_name}: Tier group not found for {current_date_str}. Skipping rate calculation for this date.") # <-- Log warning
                    # Option: Create a result row indicating missing tier?
                    continue # Skip this date if no tier

                # Check for event multiplier for this date
                event_multiplier = None
                if event_multiplier_map and current_date_str in event_multiplier_map:
                    event_multiplier = event_multiplier_map[current_date_str]

                for listing_id in listing_ids_for_property:
                    rate_group_key = calculator._get_rate_group_for_listing_id(listing_id, prop_config)
                    if not rate_group_key:
                         # st.warning(f"Rate group key not found for listing {listing_id} in property {prop_name}. Skipping.")
                         logging.warning(f"Property {prop_name}: Rate group key not found for listing {listing_id}. Skipping.") # <-- Log warning
                         continue

                    suggested_rate = None
                    error_msg = None
                    flag = '' # Placeholder for flag logic
                    baseline = 0.0 # Placeholder for baseline logic
                    occ_curr = occupancy_pct  # Assign property-wide occupancy directly
                    occ_hist = 0.0 # Placeholder
                    pace = 0.0 # Placeholder
                    calculated_tier = None # Initialize calculated tier

                    # --- Check booking status from pl_daily data FIRST (before rate calculation) ---
                    # This ensures booking status is independent of rate calculation errors
                    is_booked = False
                    try:
                        if pl_df is not None:
                            listing_data = pl_df[
                                (pl_df['Listing ID'].astype(str) == listing_id) & 
                                (pl_df['Date_clean'] == current_date_str)
                            ]
                            
                            if not listing_data.empty:
                                row = listing_data.iloc[0]
                                vacant_units = row.get('Vacant Units', 0)
                                is_booked = vacant_units == 0
                                logging.info(f"DEBUG: Listing {listing_id} on {current_date_str} - Vacant Units: {vacant_units}, Is Booked: {is_booked}")
                            else:
                                logging.warning(f"DEBUG: No pl_daily data found for {listing_id} on {current_date_str}")
                        else:
                            logging.warning(f"DEBUG: pl_daily data not loaded for {prop_name}")
                            # Fallback to booked_blocked_set check when pl_daily data is not available
                            is_booked = (listing_id, current_date_str) in booked_blocked_set
                    except Exception as e:
                        logging.error(f"Error checking booking status for {listing_id} on {current_date_str}: {e}")
                        # Fallback to booked_blocked_set check
                        is_booked = (listing_id, current_date_str) in booked_blocked_set
                    
                    if is_booked:
                        flag = '🔒 Booked'
                        # Skip rate calculation, set rates to None
                        suggested_rate = None
                        adjusted_rate = None # Not applicable
                        calculated_tier = None # Not applicable
                        error_msg = None # Not applicable
                        logging.info(f"DEBUG: Listing {listing_id} on {current_date_str} is BOOKED (from pl_daily data)")
                    else:
                        logging.info(f"DEBUG: Listing {listing_id} on {current_date_str} is NOT booked (from pl_daily data)")
                        # --- Proceed with rate calculation only if not booked ---

                        # Check advanced adjustment rules first
                        # Now returns a tuple: (rate, tier)
                        adjusted_rate, calculated_tier_from_adjustment = calculator.apply_advanced_rules(
                            current_date=current_date_obj,
                            listing_id=listing_id,
                            occupancy_pct=occupancy_pct,
                            rate_table_df=rate_table_df,
                            date_tier_map=date_tier_map,
                            booked_blocked_set=booked_blocked_set,
                            booking_window_label=booking_window,
                            property_config=prop_config,
                            property_name=prop_name,
                            today=today
                        )

                        if adjusted_rate is not None:
                            suggested_rate = adjusted_rate
                            flag = '↕️'
                            # Use the tier returned by the adjustment rule logic
                            calculated_tier = calculated_tier_from_adjustment
                        else:
                            # Standard lookup if no adjustment rule
                            suggested_rate, calculated_tier, error_msg = calculator.lookup_rate(
                                rate_table_df=rate_table_df,
                                tier_group=tier_group,
                                day_group=day_group,
                                booking_window=booking_window,
                                occupancy_pct=occupancy_pct,
                                urgency_band=urgency_band,
                                rate_group_key=rate_group_key
                            )

                        # Apply event multiplier AFTER base rate calculation (adjustment or lookup)
                        if suggested_rate is not None and event_multiplier is not None:
                            suggested_rate *= event_multiplier
                            # Prepend event flag, keep existing flags if any
                            flag = "🗓️ " + flag

                        if error_msg:
                            # Rate lookup error - but we know the listing is available
                            logging.warning(f"Rate lookup error for Prop:{prop_name} Listing:{listing_id} Date:{current_date_str} - {error_msg}")
                            flag = '❌ Error' # Indicate lookup error
                            suggested_rate = None # Ensure rate is None on error

                    # Generate a unique ID for this rate instance
                    # Combine key elements for a somewhat readable ID
                    rate_id = f"rate_{prop_name}_{listing_id}_{current_date_str}_{uuid.uuid4().hex[:4]}"

                    # Find listing name from config (Corrected lookup for list of dicts)
                    listing_name = next((item.get('name', listing_id) for item in prop_config.get('listings', []) if str(item.get('id')) == listing_id), listing_id) # Fallback to ID

                    # Get live rates data for this listing and date
                    live_rate_key = f"{listing_id}_{current_date_str}"
                    live_rate_data = live_rates_map.get(live_rate_key, {})
                    live_rate = live_rate_data.get('price', 0.0)
                    min_stay = live_rate_data.get('min_stay', 1)  # Default to 1 if not found

                    # TODO: Implement actual logic for Baseline, Occ% Hist, Pace, Flagging
                    # These might require more historical data loading or comparison logic

                    # Create result row
                    result_row = {
                        '_id': rate_id,
                        'Date': current_date_obj,
                        'Unit Pool': prop_name, # Assign prop_name (e.g., 'fb1') to Unit Pool
                        'listing_name': listing_name, # Assign looked-up name here
                        'Suggested': suggested_rate,
                        'Flag': flag.strip(), # Remove trailing space if only event flag
                        'Baseline': baseline,
                        'Occ% (Curr)': occ_curr,
                        'Occ% (Hist)': occ_hist,
                        'Pace': pace,
                        'Editable Price': suggested_rate if suggested_rate is not None else 0.0, # Default editable to suggested
                        'Live Rate $': live_rate,  # Add live rate from overrides
                        'Min Stay': min_stay,  # Add minimum stay from overrides
                        'Status': 'Needs Review',
                        # Include raw data for potential detail view needs?
                        'property': prop_name,
                        'listing_id': listing_id,
                        'tier_group': tier_group,
                        'day_group': day_group,
                        'booking_window': booking_window,
                        'urgency_band': urgency_band,
                        'lookup_error': error_msg,
                        'calculated_tier': calculated_tier, # Store the specific calculated tier
                        'tier_group': tier_group, # Keep original tier_group for reference if needed
                        'day_group': day_group,
                    }

                    # Add to full dataset for calculations
                    full_dataset_results.append(result_row)

                    # Add ALL results to display (frontend will filter as needed)
                    all_results.append(result_row)

        except (FileNotFoundError, KeyError, ValueError) as e:
            st.error(f"Error processing property {prop_name}: {e}")
            logging.error(f"Error processing property {prop_name}: {e}") # Log main error
            logging.error(f"{traceback.format_exc()}") # Log traceback separately
            traceback.print_exc() # Print full traceback for debugging
            continue # Skip to next property on error
        except Exception as e:
            st.error(f"Unexpected error processing property {prop_name}: {e}")
            logging.error(f"Unexpected error processing property {prop_name}: {e}") # Log main error
            logging.error(f"{traceback.format_exc()}") # Log traceback separately
            traceback.print_exc()
            continue

    if not all_results:
        st.warning("No rate results were generated. Check configuration and data files.")
        logging.warning("No rate results were generated.") # <-- Log warning
        return None

    logging.info(f"--- Rate calculation complete. {len(all_results)} display entries, {len(full_dataset_results)} total entries generated. ---") # <-- Log info
    
    # Store full dataset in session state for calculations
    if hasattr(st, 'session_state'):
        st.session_state.full_dataset_df = pd.DataFrame(full_dataset_results)
        logging.info(f"Full dataset stored in session state with {len(full_dataset_results)} entries")
    
    results_df = pd.DataFrame(all_results)
    return results_df


def trigger_low_occupancy_data_generation(property_selection: list, start_date: datetime.date, end_date: datetime.date) -> Optional[pd.DataFrame]:
    """
    Simplified data generation for low occupancy analysis.
    Works directly with pl_daily data without requiring rate tables.
    """
    all_properties_config = load_properties_config()
    if not all_properties_config:
        print("❌ Failed to load properties configuration.")
        return None

    all_results = []
    today = datetime.date.today()

    for prop_name in property_selection:
        if prop_name not in all_properties_config:
            print(f"⚠️  Configuration not found for property: {prop_name}. Skipping.")
            continue

        prop_config = all_properties_config[prop_name]
        listing_ids_for_property = [str(listing['id']) for listing in prop_config.get('listings', []) if 'id' in listing]

        if not listing_ids_for_property:
            print(f"⚠️  No listing IDs found in config for property: {prop_name}. Skipping.")
            continue

        try:
            # Load pl_daily data
            pl_daily_path = f"data/{prop_name}/pl_daily_{prop_name}.csv"
            if not Path(pl_daily_path).exists():
                print(f"⚠️  pl_daily file not found: {pl_daily_path}. Skipping {prop_name}.")
                continue

            pl_df = pd.read_csv(pl_daily_path)
            # Parse date column - handle ISO format with T separator
            pl_df['Date'] = pd.to_datetime(pl_df['Date']).dt.date
            # Also handle string dates if needed
            if pl_df['Date'].isna().any():
                # Try extracting date part from ISO string
                pl_df['Date'] = pd.to_datetime(pl_df['Date'].astype(str).str.split('T').str[0]).dt.date
            
            # Filter to date range
            pl_df = pl_df[(pl_df['Date'] >= start_date) & (pl_df['Date'] <= end_date)]
            
            if pl_df.empty:
                print(f"⚠️  No data in date range for {prop_name}.")
                continue

            # Calculate property-wide occupancy for each date
            # Group by date and calculate total occupancy
            total_units = prop_config.get('total_units')
            if not total_units:
                # Sum units from listings
                total_units = sum(listing.get('units', 1) for listing in prop_config.get('listings', []))
            
            if total_units == 0:
                print(f"⚠️  Total units is 0 for {prop_name}. Skipping.")
                continue

            # Calculate occupancy by date
            occupancy_by_date = {}
            for date_val in pl_df['Date'].unique():
                date_data = pl_df[pl_df['Date'] == date_val]
                total_vacant = date_data['Vacant Units'].sum()
                occupied_units = total_units - total_vacant
                occupancy_pct = (occupied_units / total_units) * 100 if total_units > 0 else 0
                occupancy_by_date[date_val] = occupancy_pct

            # Process each listing and date
            for listing_id in listing_ids_for_property:
                listing_name = next(
                    (item.get('name', listing_id) for item in prop_config.get('listings', []) 
                     if str(item.get('id')) == listing_id), 
                    listing_id
                )

                listing_data = pl_df[pl_df['Listing ID'].astype(str) == listing_id]
                
                for _, row in listing_data.iterrows():
                    date_val = row['Date']
                    if date_val < start_date or date_val > end_date:
                        continue
                    
                    # Get property-wide occupancy
                    occ_curr = occupancy_by_date.get(date_val, 0.0)
                    
                    # Get listing-specific data
                    vacant_units = row.get('Vacant Units', 0)
                    is_booked = vacant_units == 0
                    
                    # Get live rate if available (from nightly overrides)
                    live_rate = 0.0
                    min_stay = 1
                    live_rates_filename = f"{prop_name}_nightly_pulled_overrides.csv"
                    live_rates_path = Path("data") / prop_name / live_rates_filename
                    if live_rates_path.exists():
                        try:
                            live_rates_df = pd.read_csv(live_rates_path)
                            live_rates_df = live_rates_df.astype({'listing_id': str, 'date': str})
                            date_str = date_val.strftime('%Y-%m-%d')
                            matching = live_rates_df[
                                (live_rates_df['listing_id'] == listing_id) & 
                                (live_rates_df['date'] == date_str)
                            ]
                            if not matching.empty:
                                live_rate = float(matching.iloc[0].get('price', 0.0))
                                min_stay = int(matching.iloc[0].get('min_stay', 1))
                        except Exception:
                            pass

                    result_row = {
                        'Date': date_val,
                        'Unit Pool': prop_name,
                        'listing_name': listing_name,
                        'listing_id': listing_id,
                        'Occ% (Curr)': occ_curr,
                        'Live Rate $': live_rate,
                        'Suggested': live_rate,  # Use live rate as suggested for low occupancy tool
                        'Min Stay': min_stay,
                        'Vacant Units': vacant_units,
                        'Flag': '🔒 Booked' if is_booked else '',
                    }
                    all_results.append(result_row)

        except Exception as e:
            print(f"❌ Error processing property {prop_name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    if not all_results:
        print("❌ No data generated. Please check your property selection and date range.")
        return None

    results_df = pd.DataFrame(all_results)
    return results_df


def get_listing_info(listing_id: str) -> tuple:
    """Get listing name and PMS for a given listing ID"""
    try:
        properties_config = load_properties_config()
        if not properties_config:
            return "Unknown", "unknown"
            
        # Search through all properties for the listing
        for property_data in properties_config.values():
            for listing in property_data.get('listings', []):
                if listing['id'] == listing_id:
                    return listing.get('name', 'Unknown'), property_data.get('pms', 'unknown')
        
        return "Unknown", "unknown"
    except Exception:
        return "Unknown", "unknown"

def _normalize_to_date(date_value):
    """Convert various date representations to datetime.date"""
    if date_value is None:
        return None
    try:
        if isinstance(date_value, datetime.date) and not isinstance(date_value, datetime.datetime):
            return date_value
        if isinstance(date_value, datetime.datetime):
            return date_value.date()
        # Handle pandas Timestamp or numpy datetime64
        if hasattr(date_value, "to_pydatetime"):
            return date_value.to_pydatetime().date()
        # Handle string in ISO/date formats
        return pd.to_datetime(date_value).date()
    except Exception:
        return None

def get_batna_for_listing(listing_id: str, date_value=None) -> Optional[float]:
    """Get BATNA value for a specific listing ID, optionally date-aware"""
    try:
        properties_config = load_properties_config()
        if not properties_config:
            return None
        
        target_date = _normalize_to_date(date_value)
            
        # Search through all properties for the listing
        for property_data in properties_config.values():
            for listing in property_data.get('listings', []):
                if listing['id'] == listing_id:
                    # If split BATNA provided, choose weekday/weekend based on date
                    batna_weekday = listing.get('batna_weekday')
                    batna_weekend = listing.get('batna_weekend')
                    if target_date and (batna_weekday is not None or batna_weekend is not None):
                        weekday_idx = target_date.weekday() # Mon=0
                        is_weekend = weekday_idx in (4, 5) # Fri, Sat
                        if is_weekend and batna_weekend is not None:
                            return batna_weekend
                        if not is_weekend and batna_weekday is not None:
                            return batna_weekday
                    return listing.get('batna')
        
        return None
    except Exception:
        return None

def get_listing_batna_info(listing_id: str, date_value=None) -> tuple:
    """Get listing name, PMS, and BATNA value for a given listing ID"""
    try:
        properties_config = load_properties_config()
        if not properties_config:
            return "Unknown", "unknown", None
        
        target_date = _normalize_to_date(date_value)
            
        # Search through all properties for the listing
        for property_data in properties_config.values():
            for listing in property_data.get('listings', []):
                if listing['id'] == listing_id:
                    batna_value = get_batna_for_listing(listing_id, target_date)
                    return (
                        listing.get('name', 'Unknown'), 
                        property_data.get('pms', 'unknown'),
                        batna_value
                    )
        
        return "Unknown", "unknown", None
    except Exception:
        return "Unknown", "unknown", None

def apply_batna_to_selection(selected_rows, batna_type: str, amount: float = 0) -> list:
    """Apply BATNA logic to selected rows
    
    Args:
        selected_rows: List of selected data rows (from Streamlit session state)
        batna_type: "batna" or "batna_plus"
        amount: Amount to add to BATNA (for batna_plus)
    
    Returns:
        List of updates to apply
    """
    updates = []
    
    try:
        for row in selected_rows:
            listing_id = row.get('listing_id')
            if not listing_id:
                continue
                
            # Get BATNA value for this listing
            batna_value = get_batna_for_listing(listing_id, row.get('Date'))
            if batna_value is None:
                st.warning(f"No BATNA value found for listing {listing_id}")
                continue
            
            # Calculate new rate based on BATNA type
            if batna_type == "batna":
                new_rate = batna_value
                reason = "BATNA Rate Applied"
            elif batna_type == "batna_plus":
                new_rate = batna_value + amount
                reason = f"BATNA + ${amount:.2f} Applied"
            else:
                st.error(f"Invalid BATNA type: {batna_type}")
                continue
            
            # Create update entry
            update = {
                '_id': row.get('_id'),
                'listing_id': listing_id,
                'Date': row.get('Date'),
                'Editable Price': new_rate,
                'Status': 'Needs Review',
                'batna_applied': True,
                'batna_type': batna_type,
                'batna_value': batna_value,
                'amount_added': amount if batna_type == "batna_plus" else 0,
                'reason': reason
            }
            updates.append(update)
            
    except Exception as e:
        st.error(f"Error applying BATNA to selection: {e}")
        traceback.print_exc()
    
    return updates

def update_rates(updates: list):
    """Logs rate updates (adjustments/approvals). Enhanced with proper logging system."""
    log_file = OUTPUT_DIR / "updates_log.csv"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entries = []

    # Setup logging for price updates
    try:
        price_logger, error_logger = setup_logging()
    except Exception as e:
        st.error(f"Failed to setup logging: {e}")
        price_logger, error_logger = None, None

    for update in updates:
        # Get listing information
        listing_id = update.get('_id', update.get('listing_id'))
        listing_name, pms = get_listing_info(listing_id)
        
        # Create legacy log entry for backward compatibility
        log_entry = {
            'timestamp': now,
            'rate_id': listing_id,
            'new_price': update.get('Editable Price'),
            'new_status': update.get('Status', 'Updated')
        }
        log_entries.append(log_entry)
        
        # Log to proper pricing update log
        if price_logger and listing_id:
            try:
                # Extract date from update if available
                date_str = update.get('Date', '')
                if not date_str:
                    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
                
                log_price_update(
                    logger=price_logger,
                    listing_id=listing_id,
                    listing_name=listing_name,
                    pms_name=pms,
                    start_date=date_str,
                    end_date=date_str,
                    price=float(update.get('Editable Price', 0)),
                    currency='USD',
                    price_type='fixed',
                    minimum_stay=1,
                    reason="Manual Frontend Adjustment"
                )
            except Exception as log_error:
                st.warning(f"Failed to log price update for {listing_id}: {str(log_error)}")

    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        log_df = pd.DataFrame(log_entries)
        
        # Check if file exists to append header correctly
        write_header = not log_file.exists()
        log_df.to_csv(log_file, mode='a', header=write_header, index=False)
        return True
    except Exception as e:
        traceback.print_exc()
        st.error(f"Error logging updates to {log_file}: {e}")
        return False

def push_rates_live(approved_rate_ids: list, all_rates_df: pd.DataFrame):
    """Writes approved rates to an output CSV file."""
    if all_rates_df is None or all_rates_df.empty:
        st.error("Cannot push rates: No rate data available.")
        return False
    if not approved_rate_ids:
        st.warning("No approved rate IDs provided to push.")
        return False # Or True, depending if this is considered an error

    # Filter the DataFrame provided from the Streamlit app's session state
    rates_to_push = all_rates_df[all_rates_df['_id'].isin(approved_rate_ids)].copy()

    if rates_to_push.empty:
        st.warning("No matching rates found for the approved IDs provided.")
        return False

    # Define output file path
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"pushed_rates_{timestamp}.csv"

    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True) # Ensure directory exists
        # Select and order columns for output (adjust as needed)
        output_columns = ['Date', 'Unit Pool', 'listing_id', 'Editable Price', 'Status', '_id']
        # Filter columns, handling potential missing ones gracefully
        output_columns = [col for col in output_columns if col in rates_to_push.columns]
        rates_to_push[output_columns].to_csv(output_file, index=False)
        print(f"Successfully wrote {len(rates_to_push)} approved rates to {output_file}")
        return True
    except Exception as e:
        st.error(f"Error writing approved rates to {output_file}: {e}")
        traceback.print_exc()
        return False 