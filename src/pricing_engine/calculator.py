# src/pricing_engine/calculator.py

import pandas as pd
import datetime
from typing import Optional, Dict, Any, Tuple, Set
import numpy as np

# Assuming utils.py is in the same directory or Python path is set correctly
from . import utils # Use relative import within the package

# Import logging functions
try:
    from rates.logging_setup import setup_logging, log_price_update
except ImportError:
    # Fallback if rates module is not available
    def setup_logging():
        return None, None
    def log_price_update(*args, **kwargs):
        pass

# Rule engine import removed - will be added when ready for integration

def _get_listing_info(listing_id: str, property_config: dict) -> tuple:
    """Get listing name and PMS for a given listing ID"""
    try:
        # Search through all properties for the listing
        for property_data in property_config.values() if isinstance(property_config, dict) else [property_config]:
            for listing in property_data.get('listings', []):
                if listing['id'] == listing_id:
                    return listing.get('name', 'Unknown'), property_data.get('pms', 'unknown')
        
        return "Unknown", "unknown"
    except Exception:
        return "Unknown", "unknown"

def _get_rate_group_for_listing_id(listing_id: str, property_config: dict) -> Optional[str]:
    """
    Finds the rate group key (e.g., 'rate_1', 'rate_2') for a given listing ID
    based on the property's rate_group_mapping configuration (which maps keys to IDs).

    Args:
        listing_id: The ID of the listing.
        property_config: The configuration dictionary for the specific property.

    Returns:
        The rate group key string (which should match a column name in the
        rate table) or None if the listing ID is not found in any mapping.
    """
    rate_mapping = property_config.get('rate_group_mapping', {})
    for group_key, ids_in_group in rate_mapping.items():
        if listing_id in ids_in_group: # Check if ID is in the list
            return group_key # Returns the key like 'rate_1'
    # Optional: Add warning if ID not found
    # print(f"Warning: Listing ID '{listing_id}' not found in any rate_group_mapping for property. Cannot determine rate column.")
    return None

def lookup_rate(
    rate_table_df: pd.DataFrame,
    tier_group: str,
    day_group: str,
    booking_window: str,
    occupancy_pct: float,
    urgency_band: Optional[str],
    rate_group_key: str # The key like 'rate_small' derived from listing
) -> Tuple[Optional[float], Optional[str], Optional[str]]: # Return tuple: (rate, calculated_tier, error_message)
    """
    Looks up the suggested rate in the rate table based on provided factors.

    Args:
        rate_table_df: The DataFrame containing rate rules for the property.
        tier_group: The tier group string (e.g., 'T0', 'T1-T3').
        day_group: The day group string (e.g., 'Mon-Wed').
        booking_window: The booking window label (e.g., '0-9 Days (W1)').
        occupancy_pct: The calculated occupancy percentage for the date.
        urgency_band: The urgency band string (e.g., '0-1') or None/empty string.
        rate_group_key: The specific rate column key (e.g., 'rate_small') to use.

    Returns:
        A tuple containing:
        - The suggested rate as a float, or None if no matching rule is found.
        - The 'Calculated Tier' string from the matching rule, or None.
        - An error message string if lookup fails, otherwise None.
    """
    calculated_tier = None # Initialize
    if not tier_group or not rate_group_key:
        error_msg = f"Lookup failed: Invalid input (Tier: {tier_group}, RateKey: {rate_group_key})"
        return None, calculated_tier, error_msg

    # Ensure urgency_band is either a valid string or treated as 'match any'
    # Handle None or empty string for urgency band matching
    urgency_filter_active = bool(urgency_band) # True if urgency_band is not None/empty

    # Filter the DataFrame - Use inclusive boundaries for occupancy
    # ROUND occupancy_pct to nearest integer for matching
    occupancy_pct_rounded = round(occupancy_pct)
    mask = (
        (rate_table_df['tier_group'] == tier_group) &
        (rate_table_df['day_group'] == day_group) &
        (rate_table_df['booking_window'] == booking_window) &
        (rate_table_df['occupancy_min_pct'] <= occupancy_pct_rounded) &
        (rate_table_df['occupancy_max_pct'] >= occupancy_pct_rounded)
    )

    # Add urgency band filter conditionally
    if urgency_filter_active:
        # Assumes rate table has an 'Urgency Breakdown' column, handle missing values
        mask &= (rate_table_df['Urgency Breakdown'].fillna('') == urgency_band)
    else:
        # If no urgency band applies to the request, match rows where
        # the table's urgency band is also empty/null (standard rule)
        mask &= (rate_table_df['Urgency Breakdown'].fillna('') == '')


    matching_rows = rate_table_df[mask]

    if not matching_rows.empty:
        first_match = matching_rows.iloc[0]
        try:
            rate_value = first_match[rate_group_key]
            calculated_tier = first_match.get('Calculated Tier') # Get the Calculated Tier
            rate_numeric = pd.to_numeric(rate_value, errors='coerce')
            if pd.isna(rate_numeric):
                error_msg = f"Lookup Error: Non-numeric rate value '{rate_value}' found for RateKey: {rate_group_key} with inputs Tier:{tier_group}, Day:{day_group}, Win:{booking_window}, Occ:{occupancy_pct:.2f}%, Urg:{urgency_band}"
                return None, calculated_tier, error_msg # Return tier even if rate invalid
            else:
                return rate_numeric, calculated_tier, None # Success
        except KeyError as e:
            error_msg = f"Lookup Error: Rate column '{e}' not found in rate table."
            calculated_tier = first_match.get('Calculated Tier') # Still try to get tier
            return None, calculated_tier, error_msg
        except Exception as e:
            error_msg = f"Lookup Error: Unexpected error retrieving rate value: {e}"
            calculated_tier = first_match.get('Calculated Tier') # Still try to get tier
            return None, calculated_tier, error_msg
    else:
        error_msg = f"Lookup Failed: No rule found for Tier:{tier_group}, Day:{day_group}, Win:{booking_window}, Occ:{occupancy_pct:.2f}%, Urg:{urgency_band}, RateCol:{rate_group_key}"
        return None, calculated_tier, error_msg


def get_adjusted_rate(
    ref_date: datetime.date,
    target_day_group: str, # Day group to use for lookup (e.g., 'Mon-Wed')
    listing_id: str,
    multiplier: float,
    occupancy_pct: float, # Occupancy for the ORIGINAL date being priced
    rate_table_df: pd.DataFrame,
    date_tier_map: Dict[str, str],
    booking_window_label: str, # Booking window for the ORIGINAL date
    property_config: dict,
    today: datetime.date # Today's date for potential urgency calc on ref_date
) -> Tuple[Optional[float], Optional[str]]: # Return rate AND calculated tier
    """
    Calculates an adjusted rate based on a reference date's tier and other factors.
    Used by the Thursday/Sunday rules.

    Args:
        ref_date: The reference date (e.g., Wednesday for Thursday rule) to get the tier from.
        target_day_group: The day group to use for the lookup (typically 'Mon-Wed').
        listing_id: The specific listing ID.
        multiplier: The factor to multiply the looked-up rate by (e.g., 1.1, 1.2).
        occupancy_pct: The occupancy percentage for the *original* date being priced.
        rate_table_df: The rate table DataFrame.
        date_tier_map: Map of date strings to tier groups.
        booking_window_label: The booking window label for the *original* date.
        property_config: Configuration for the property (for rate group mapping).
        today: Today's date for urgency band calculation based on ref_date.

    Returns:
        A tuple containing the calculated adjusted rate (or None) and the
        calculated tier string from the underlying lookup (or None).
    """
    ref_date_str = utils.format_date(ref_date)
    ref_tier_group = date_tier_map.get(ref_date_str)

    if not ref_tier_group:
        print(f"Warning: Tier group not found for reference date {ref_date_str} during adjustment calculation.")
        return None, None # Return None for both rate and tier

    # Use the ID-based lookup function
    rate_group_key = _get_rate_group_for_listing_id(listing_id, property_config)
    if not rate_group_key:
        # Consider adding a warning here if the ID lookup fails
        print(f"Warning: Failed to find rate group for Listing ID '{listing_id}' during adjustment.")
        return None, None # Return None for both rate and tier

    # Determine if urgency applies based on the REFERENCE date's tier and window/occupancy
    ref_urgency_band = ""
    # Get urgency configuration from property config
    urgency_config = property_config.get('urgency_configuration', {})
    if urgency_config:  # Only check urgency if property has urgency configuration
        tier_groups = urgency_config.get('tier_groups', [])
        urgency_window_label = urgency_config.get('booking_window_label', '')
        max_occupancy_pct = urgency_config.get('max_occupancy_pct', 0)
        
        # Check if urgency should apply based on property's configuration
        if (tier_groups and ref_tier_group in tier_groups and 
            urgency_window_label and booking_window_label.endswith(f"({urgency_window_label})") and 
            max_occupancy_pct > 0 and occupancy_pct <= max_occupancy_pct):
       # Urgency band itself depends on days between ref_date and today
            ref_urgency_band = utils.get_urgency_band(ref_date, today, property_config)

    # Perform the lookup using reference date's tier, target day group, original occupancy, etc.
    # IMPORTANT: get_adjusted_rate now uses lookup_rate internally.
    # We only care about the rate here, not the error message from the lookup.
    # Error handling for the base lookup should happen in the main script.
    base_rate, calculated_tier, _ = lookup_rate( # Unpack the tuple, ignore the error message here
        rate_table_df=rate_table_df,
        tier_group=ref_tier_group,
        day_group=target_day_group, # Use the specified day group ('Mon-Wed')
        booking_window=booking_window_label, # Use original booking window
        occupancy_pct=occupancy_pct, # Use original occupancy
        urgency_band=ref_urgency_band, # Urgency determined by ref_date context
        rate_group_key=rate_group_key
    )

    if base_rate is not None and pd.notna(base_rate): # Check if lookup succeeded and is not NaN
        # Return the adjusted rate AND the calculated tier from the lookup
        return base_rate * multiplier, calculated_tier
    else:
        # Return None for rate, but still return the tier if lookup_rate provided one
        return None, calculated_tier


def _check_condition(
    condition_config: Optional[Dict[str, Any]],
    current_date: datetime.date,
    listing_id: str,
    booked_blocked_set: Set[Tuple[str, str]]
) -> bool:
    """
    Checks if a single condition is met.
    
    Note: The booked_blocked_set contains only FULLY booked listings (Vacant Units = 0),
    not partially booked listings.
    """
    if condition_config is None:
        return True # Default action condition

    cond_type = condition_config.get('type')

    if cond_type == 'adjacent_day_booked':
        day_offset = condition_config.get('day_offset')
        if day_offset is None:
            print(f"Warning: Missing 'day_offset' for 'adjacent_day_booked' condition. Rule skipped.")
            return False # Invalid condition config
        adjacent_date = utils.add_days(current_date, day_offset)
        adjacent_date_str = utils.format_date(adjacent_date)
        return (listing_id, adjacent_date_str) in booked_blocked_set
    elif cond_type == 'upcoming_weekend':
        # Check if this is the immediate upcoming weekend
        # Get today's date (we'll need to pass this as a parameter)
        from datetime import datetime
        today = datetime.now().date()
        
        # Calculate days until this Friday
        current_weekday = current_date.weekday()
        days_until_friday = (4 - today.weekday()) % 7  # 4 = Friday
        if days_until_friday == 0:  # Today is Friday
            days_until_friday = 7  # Next Friday
        
        # Calculate the immediate upcoming Friday
        upcoming_friday = today + datetime.timedelta(days=days_until_friday)
        upcoming_saturday = upcoming_friday + datetime.timedelta(days=1)
        
        # Return True only if current_date is the upcoming Friday or Saturday
        return current_date in [upcoming_friday, upcoming_saturday]
    # --- Add other condition type checks here in the future ---
    else:
        print(f"Warning: Unknown condition type '{cond_type}'. Rule skipped.")
        return False # Unknown condition type

def apply_adjustment_rules(
    current_date: datetime.date,
    listing_id: str,
    occupancy_pct: float, # Occupancy for current_date
    rate_table_df: pd.DataFrame,
    date_tier_map: Dict[str, str],
    booked_blocked_set: Set[Tuple[str, str]],
    booking_window_label: str, # Booking window for current_date
    property_config: dict,
    today: datetime.date # Today's date for urgency calcs
) -> Tuple[Optional[float], Optional[str]]: # Return rate AND calculated tier
    """
    Checks and applies adjustment rules defined in the property configuration.

    Args:
        current_date: The date for which the rate is being calculated.
        listing_id: The specific listing ID.
        occupancy_pct: Occupancy percentage for current_date.
        rate_table_df: Rate table DataFrame.
        date_tier_map: Map of date strings to tiers.
        booked_blocked_set: Set of ('listing_id', 'YYYY-MM-DD') for booked/blocked dates.
        booking_window_label: Booking window label for current_date.
        property_config: Property configuration including 'adjustment_rules'.
        today: Today's date.

    Returns:
        A tuple containing the adjusted rate (or None) and the associated
        calculated tier string (or None).
    """
    rules = property_config.get('adjustment_rules', [])
    if not rules:
        return None, None # No rules defined

    current_weekday = current_date.weekday()

    for rule in rules:
        if rule.get('target_weekday') == current_weekday:
            all_conditions_met = True
            for condition_config in rule.get('conditions', []):
                if not _check_condition(condition_config, current_date, listing_id, booked_blocked_set):
                    all_conditions_met = False
                    break

            if all_conditions_met:
                print(f"🔍 DEBUG: Rule '{rule.get('name', 'Unnamed Rule')}' conditions met for {listing_id} on {utils.format_date(current_date)}")
                selected_action = None
                for action in rule.get('actions', []):
                    nested_condition_config = action.get('condition')
                    if _check_condition(nested_condition_config, current_date, listing_id, booked_blocked_set):
                        selected_action = action
                        break

                if selected_action:
                    print(f"Applying rule '{rule.get('name', 'Unnamed Rule')}' for Listing ID {listing_id} on {utils.format_date(current_date)}")
                    multiplier = selected_action.get('multiplier')
                    ref_day_offset = selected_action.get('reference_day_offset')
                    lookup_day_group = selected_action.get('lookup_day_group')

                    if multiplier is None or ref_day_offset is None or lookup_day_group is None:
                        print(f"Warning: Rule '{rule.get('name', 'Unnamed Rule')}' action is missing required parameters. Skipping.")
                        continue

                    ref_date = utils.add_days(current_date, ref_day_offset)

                    # Get both adjusted rate and the tier from the underlying lookup
                    adjusted_rate, calculated_tier = get_adjusted_rate(
                        ref_date=ref_date,
                        target_day_group=lookup_day_group,
                        listing_id=listing_id,
                        multiplier=multiplier,
                        occupancy_pct=occupancy_pct,
                        rate_table_df=rate_table_df,
                        date_tier_map=date_tier_map,
                        booking_window_label=booking_window_label,
                        property_config=property_config,
                        today=today
                    )

                    # If adjustment succeeded, log the rule application and return rate AND the determined tier
                    if adjusted_rate is not None:
                        # Log the rule-based adjustment
                        try:
                            price_logger, error_logger = setup_logging()
                            if price_logger:
                                listing_name, pms = _get_listing_info(listing_id, property_config)
                                log_price_update(
                                    logger=price_logger,
                                    listing_id=listing_id,
                                    listing_name=listing_name,
                                    pms_name=pms,
                                    start_date=utils.format_date(current_date),
                                    end_date=utils.format_date(current_date),
                                    price=float(adjusted_rate),
                                    currency='USD',
                                    price_type='fixed',
                                    minimum_stay=1,
                                    reason=f"Rule: {rule.get('name', 'Unnamed Rule')}"
                                )
                        except Exception as log_error:
                            print(f"Warning: Failed to log rule adjustment: {str(log_error)}")
                        
                        return adjusted_rate, calculated_tier
                    # If adjustment failed, we might still have a tier from lookup, but rate is None
                    # We implicitly continue to the next rule or fall through
                else:
                     print(f"Warning: Rule '{rule.get('name', 'Unnamed Rule')}' triggered, but no valid action found for Listing ID {listing_id} on {utils.format_date(current_date)}")

    # If no rules applied or succeeded, return None for both
    return None, None

def apply_min_stay_adjustment_rules(
    current_date: datetime.date,
    listing_id: str,
    booked_blocked_set: Set[Tuple[str, str]],
    property_config: dict
) -> Optional[Dict[str, Any]]:
    """
    Checks and applies minimum stay adjustment rules defined in the property configuration.
    
    Args:
        current_date: The date for which the adjustment is being calculated.
        listing_id: The specific listing ID.
        booked_blocked_set: Set of ('listing_id', 'YYYY-MM-DD') for booked/blocked dates.
        property_config: Property configuration including 'adjustment_rules'.
        
    Returns:
        A dictionary containing adjustment information or None if no adjustment applies.
        Format: {
            'min_stay_adjustment': int,  # New minimum stay value
            'target_adjacent_days': List[int],  # Days to apply adjustment to
            'rule_name': str  # Name of the rule that triggered
        }
    """
    rules = property_config.get('adjustment_rules', [])
    if not rules:
        return None # No rules defined

    current_weekday = current_date.weekday()

    for rule in rules:
        if rule.get('target_weekday') == current_weekday:
            all_conditions_met = True
            for condition_config in rule.get('conditions', []):
                if not _check_condition(condition_config, current_date, listing_id, booked_blocked_set):
                    all_conditions_met = False
                    break

            if all_conditions_met:
                selected_action = None
                for action in rule.get('actions', []):
                    nested_condition_config = action.get('condition')
                    if _check_condition(nested_condition_config, current_date, listing_id, booked_blocked_set):
                        selected_action = action
                        break

                if selected_action:
                    min_stay_adjustment = selected_action.get('min_stay_adjustment')
                    target_adjacent_days = selected_action.get('target_adjacent_days')
                    
                    if min_stay_adjustment is not None and target_adjacent_days is not None:
                        print(f"Applying min stay rule '{rule.get('name', 'Unnamed Rule')}' for Listing ID {listing_id} on {utils.format_date(current_date)}")
                        return {
                            'min_stay_adjustment': min_stay_adjustment,
                            'target_adjacent_days': target_adjacent_days,
                            'rule_name': rule.get('name', 'Unnamed Rule')
                        }

    # If no rules applied or succeeded, return None
    return None

def apply_advanced_rules(
    current_date: datetime.date,
    listing_id: str,
    occupancy_pct: float,
    rate_table_df: pd.DataFrame,
    date_tier_map: Dict[str, str],
    booked_blocked_set: Set[Tuple[str, str]],
    booking_window_label: str,
    property_config: dict,
    property_name: str,
    today: datetime.date
) -> Tuple[Optional[float], Optional[str]]:
    """
    Apply the advanced rule engine for complex pricing adjustments.
    
    NOTE: This function is currently disabled - rule engine implementation
    will be added when ready for integration.
    
    Args:
        current_date: The date for which the rate is being calculated.
        listing_id: The specific listing ID.
        occupancy_pct: Occupancy percentage for current_date.
        rate_table_df: Rate table DataFrame.
        date_tier_map: Map of date strings to tiers.
        booked_blocked_set: Set of ('listing_id', 'YYYY-MM-DD') for booked/blocked dates.
        booking_window_label: Booking window label for current_date.
        property_config: Property configuration.
        property_name: Name of the property (e.g., 'atx1', 'fb1').
        today: Today's date.
    
    Returns:
        A tuple containing the adjusted rate (or None) and the associated
        calculated tier string (or None).
    """
    # Rule engine implementation disabled - will be added when ready
    return None, None
