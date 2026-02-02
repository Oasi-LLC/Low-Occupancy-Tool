# src/pricing_engine/utils.py

import datetime

def format_date(d: datetime.date) -> str:
    """
    Formats a date or datetime object into a 'YYYY-MM-DD' string.

    Args:
        d: The date or datetime object to format.

    Returns:
        The formatted date string.

    Raises:
        TypeError: If the input is not a date or datetime object.
    """
    if not isinstance(d, (datetime.date, datetime.datetime)):
        raise TypeError("Input must be a datetime.date or datetime.datetime object")
    return d.strftime('%Y-%m-%d')

def add_days(d: datetime.date, days: int) -> datetime.date:
    """
    Adds a specified number of days to a date object.

    Args:
        d: The starting date or datetime object.
        days: The number of days to add (can be negative).

    Returns:
        A new date object representing the resulting date.

    Raises:
        TypeError: If the input date is not a date or datetime object.
    """
    if not isinstance(d, (datetime.date, datetime.datetime)):
        raise TypeError("Input date must be a datetime.date or datetime.datetime object")
    # If it's a datetime object, ensure we return only the date part
    if isinstance(d, datetime.datetime):
        d = d.date()
    return d + datetime.timedelta(days=days)

def get_day_group(d: datetime.date) -> str:
    """
    Determines the day group ('Mon-Wed', 'Thu-Sun', 'Fri-Sat') for a given date.

    Args:
        d: The date or datetime object.

    Returns:
        A string representing the day group.

    Raises:
        TypeError: If the input is not a date or datetime object.
    """
    if not isinstance(d, (datetime.date, datetime.datetime)):
        raise TypeError("Input must be a datetime.date or datetime.datetime object")
    day_of_week = d.weekday() # Monday is 0 and Sunday is 6

    if day_of_week in [0, 1, 2]: # Monday, Tuesday, Wednesday
        return 'Mon-Wed'
    elif day_of_week in [3, 6]: # Thursday, Sunday
        return 'Thu-Sun'
    else: # Friday (4), Saturday (5)
        return 'Fri-Sat'

def get_booking_window_label(target_date: datetime.date, today: datetime.date, window_definitions: list) -> str:
    """
    Calculates the booking window label based on the number of days between
    today and the target date, using definitions provided from configuration.

    Args:
        target_date: The future date for which the rate is being calculated.
        today: The current date (typically the date the script is run).
        window_definitions: A list of dictionaries, each defining a window:
                          e.g., [{\'label\': \'0-9 Days (W1)\', \'min_days\': 0, \'max_days\': 9}, ...]

    Returns:
        A string representing the booking window label, or a default/error label if none match.

    Raises:
        TypeError: If date inputs are not date or datetime objects.
        ValueError: If window_definitions is missing or invalid.
    """
    if not isinstance(target_date, (datetime.date, datetime.datetime)):
        raise TypeError("target_date must be a date or datetime object")
    if not isinstance(today, (datetime.date, datetime.datetime)):
        raise TypeError("today must be a date or datetime object")
    if not window_definitions:
        raise ValueError("Booking window definitions are missing or empty in property config.")

    # Ensure we are comparing dates only, ignoring time component
    if isinstance(target_date, datetime.datetime):
        target_date = target_date.date()
    if isinstance(today, datetime.datetime):
        today = today.date()

    diff_days = (target_date - today).days

    # Handle cases where target_date is in the past relative to today
    if diff_days < 0:
        # Find the label associated with min_days = 0 (should be the shortest window)
        for definition in window_definitions:
            if definition.get('min_days') == 0:
                return definition.get('label', 'ERROR: No 0-day window') # Return label or error
        return "ERROR: No 0-day window defined" # Fallback if no 0-day window found

    # Find the matching window definition
    for definition in window_definitions:
        min_days = definition.get('min_days')
        max_days = definition.get('max_days')
        label = definition.get('label')

        # Basic validation of the definition structure
        if min_days is None or max_days is None or label is None:
             print(f"Warning: Invalid booking window definition found: {definition}. Skipping.")
             continue

        if min_days <= diff_days <= max_days:
            return label

    # Fallback if no window matches (shouldn't happen with a proper >X days definition)
    print(f"Warning: No matching booking window definition found for diff_days={diff_days}. Using default fallback.")
    return "ERROR: No Matching Window"

def get_urgency_band(target_date: datetime.date, today: datetime.date, urgency_definitions: list) -> str:
    """
    Calculates the urgency band based on the number of days between today and
    the target date, using definitions provided from configuration.

    Args:
        target_date: The future date for which the rate is being calculated.
        today: The current date.
        urgency_definitions: A list of dictionaries defining urgency bands,
                           e.g., [{\'label\': \'0-1\', \'min_days\': 0, \'max_days\': 1}, ...]

    Returns:
        A string representing the urgency band label, or an empty string if none match or invalid config.

    Raises:
        TypeError: If date inputs are not date or datetime objects.
    """
    if not isinstance(target_date, (datetime.date, datetime.datetime)):
        raise TypeError("target_date must be a date or datetime object")
    if not isinstance(today, (datetime.date, datetime.datetime)):
        raise TypeError("today must be a date or datetime object")
    # It's okay if urgency_definitions is empty or None, we just return ""
    if not urgency_definitions:
        return "" # No definitions, no urgency band

    # Ensure we are comparing dates only
    if isinstance(target_date, datetime.datetime):
        target_date = target_date.date()
    if isinstance(today, datetime.datetime):
        today = today.date()

    diff_days = (target_date - today).days

    if diff_days < 0:
        return "" # No urgency band for past dates

    # Find the matching urgency definition
    for definition in urgency_definitions:
        min_days = definition.get('min_days')
        max_days = definition.get('max_days')
        label = definition.get('label')

        # Basic validation of the definition structure
        if min_days is None or max_days is None or label is None:
             print(f"Warning: Invalid urgency band definition found: {definition}. Skipping.")
             continue

        if min_days <= diff_days <= max_days:
            return label

    # If loop finishes without finding a match (e.g., diff_days >= 10 based on current config)
    return "" # Default to no urgency band