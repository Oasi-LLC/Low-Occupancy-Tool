#!/usr/bin/env python3
"""
Comprehensive script to generate pl_daily files for any property.
Handles both cloudbeds and hostaway PMSs correctly.
"""

import requests
from rates.config import API_KEY, BASE_URL
from datetime import datetime, timedelta
import pandas as pd
import yaml
import time
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

def get_listing_overrides(listing_id, pms, start_date, end_date):
    """Get listing overrides for the date range."""
    url = f"{BASE_URL}/listings/{listing_id}/overrides"
    headers = {
        'X-API-Key': API_KEY,
        'Content-Type': 'application/json'
    }
    params = {'pms': pms} if pms else {}
    
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    data = response.json()
    
    overrides = data.get('overrides', [])
    
    # Create a dictionary of date -> override price
    override_prices = {}
    for override in overrides:
        date = override.get('date')
        if date and start_date <= date <= end_date:
            override_prices[date] = float(override.get('price', 0))
    
    return override_prices

def get_reservations_for_listing(listing_id, pms, start_date, end_date, all_reservations):
    """Get reservations for a specific listing from the full reservation list."""
    listing_reservations = []
    for res in all_reservations:
        if res.get('listing_id') == listing_id:
            check_in = res.get('check_in')
            check_out = res.get('check_out')
            if check_in and check_out:
                # Check if reservation overlaps with date range
                if check_in <= end_date and check_out > start_date:
                    listing_reservations.append(res)
    
    return listing_reservations

def get_daily_data_for_listing(listing_id, pms, start_date, end_date):
    """Get daily data (pricing, booking status, blocking) for a listing."""
    url = f"{BASE_URL}/listing_prices"
    headers = {
        'X-API-Key': API_KEY,
        'Content-Type': 'application/json'
    }
    payload = {
        "listings": [
            {
                "id": listing_id,
                "pms": pms,
                "dateFrom": start_date,
                "dateTo": end_date
            }
        ]
    }
    
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    
    # Process daily data
    daily_data = {}
    if isinstance(data, list) and len(data) > 0:
        listing_data = data[0]
        if 'data' in listing_data:
            for entry in listing_data['data']:
                date = entry.get('date')
                if date:
                    daily_data[date] = entry
    
    return daily_data

def fetch_all_reservations(pms, start_date, end_date):
    """Fetch all reservations for the PMS and date range using pagination."""
    url = f"{BASE_URL}/reservation_data"
    headers = {
        'X-API-Key': API_KEY,
        'Content-Type': 'application/json'
    }
    limit = 100
    offset = 0
    all_reservations = []
    while True:
        params = {
            'pms': pms,
            'start_date': start_date,
            'end_date': end_date,
            'limit': limit,
            'offset': offset
        }
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        reservations = data.get('data', [])
        all_reservations.extend(reservations)
        if len(reservations) < limit:
            break
        offset += limit
    return all_reservations

def fetch_listing_data(listing, start_date, end_date, all_reservations, pms):
    """Fetch data for a single listing (to be used in parallel)."""
    listing_id = str(listing['id'])
    listing_name = listing.get('name', 'Unknown')
    units = listing.get('units', 1)
    
    print(f"  🏠 Processing {listing_name} ({listing_id}) - {units} units")
    
    # Filter reservations for this listing
    listing_reservations = [r for r in all_reservations if str(r.get('listing_id')) == listing_id]
    print(f"    📊 Found {len(listing_reservations)} reservations")
    
    # Fetch daily data for this listing
    t0 = time.time()
    daily_data = get_daily_data_for_listing(listing_id, pms, start_date, end_date)
    daily_time = time.time() - t0
    print(f"    ⏱️ Daily data fetched in {daily_time:.2f}s")
    
    # Fetch overrides for this listing
    t0 = time.time()
    override_prices = get_listing_overrides(listing_id, pms, start_date, end_date)
    overrides_time = time.time() - t0
    print(f"    ⏱️ Overrides fetched in {overrides_time:.2f}s")
    
    # Process dates for this listing
    t0 = time.time()
    listing_records = []
    current_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_datetime = datetime.strptime(end_date, '%Y-%m-%d')
    
    while current_date <= end_datetime:
        date_str = current_date.strftime('%Y-%m-%d')
        date_iso = f"{date_str}T00:00:00.000000"
        daily_info = daily_data.get(date_str, {})
        
        # Get booking status from listing_prices
        booking_status = daily_info.get('booking_status', '')
        is_booked = 'Booked' in booking_status
        
        # Count actual reservations for this date
        date_reservations = []
        for res in listing_reservations:
            check_in = res.get('check_in')
            check_out = res.get('check_out')
            booking_status_res = res.get('booking_status')
            if check_in and check_out and booking_status_res == 'booked':
                if check_in <= date_str < check_out:
                    date_reservations.append(res)
        
        # No. Booked is the count of reservations for this date
        booking_count = len(date_reservations)
        blocking_count = 1 if daily_info.get('unbookable', 0) else 0
        
        # Get revenue from override price or listing price
        revenue = override_prices.get(date_str, daily_info.get('price', 0))
        
        # Calculate derived fields
        bookable_units = units - blocking_count
        vacant_units = units - booking_count - blocking_count
        if vacant_units < 0:
            vacant_units = 0  # Prevent negative vacant units
        blocking_units = blocking_count * units
        
        pl_daily_record = {
            'Listing ID': listing_id,
            'PMS Name': pms,
            'Date': date_iso,
            'Units': units,
            'No. Booked': booking_count,
            'No. Blocked': blocking_count,
            'blocking_units': blocking_units,
            'Bookable Units': bookable_units,
            'nightly_revenue': revenue,
            'Vacant Units': vacant_units
        }
        
        listing_records.append(pl_daily_record)
        current_date += timedelta(days=1)
    
    date_loop_time = time.time() - t0
    print(f"    ⏱️ Date loop for listing took {date_loop_time:.2f}s")
    print(f"    ✅ Generated {len(listing_records)} daily records")
    
    return listing_records

def generate_pl_daily_for_property(property_key, start_date, end_date):
    """Generate pl_daily data for a specific property."""
    
    # Load property config
    with open('config/properties.yaml', 'r') as f:
        config = yaml.safe_load(f)
    
    property_config = config['properties'].get(property_key, {})
    if not property_config:
        print(f"❌ Property {property_key} not found in config")
        return None
    
    pms = property_config.get('pms', 'cloudbeds')
    listings = property_config.get('listings', [])
    property_name = property_config.get('name', property_key)
    
    print(f"🔍 Generating pl_daily data for {property_name} ({property_key})")
    print(f"📅 Date range: {start_date} to {end_date}")
    print(f"🏢 PMS: {pms}")
    print(f"🏠 Listings: {len(listings)}")
    print("=" * 60)
    
    property_start = time.time()
    
    # Get all reservations (will be filtered by listing ID later)
    t0 = time.time()
    all_reservations = fetch_all_reservations(pms, start_date, end_date)
    reservations_time = time.time() - t0
    print(f"📊 Found {len(all_reservations)} total reservations from {pms} (fetched in {reservations_time:.2f}s)\n")
    
    # Process listings in parallel
    all_records = []
    with ThreadPoolExecutor(max_workers=3) as executor:  # Limit to 3 threads to avoid rate limiting
        # Submit all listing tasks
        future_to_listing = {
            executor.submit(fetch_listing_data, listing, start_date, end_date, all_reservations, pms): listing 
            for listing in listings
        }
        
        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_listing):
            listing = future_to_listing[future]
            try:
                listing_records = future.result()
                all_records.extend(listing_records)
                listing_time = time.time() - property_start
                print(f"  ✅ {listing.get('name', 'Unknown')} processed in {listing_time:.2f}s")
            except Exception as exc:
                print(f"  ❌ {listing.get('name', 'Unknown')} generated an exception: {exc}")
    
    property_time = time.time() - property_start
    print(f"\n✅ Generated {len(all_records)} total pl_daily records (property processed in {property_time:.2f}s)")
    
    return all_records

def generate_pl_daily_for_property_batched(property_key, start_date, end_date):
    """Generate pl_daily data for onera property using batch processing to avoid rate limits."""
    
    # Load property config
    with open('config/properties.yaml', 'r') as f:
        config = yaml.safe_load(f)
    
    property_config = config['properties'].get(property_key, {})
    if not property_config:
        print(f"❌ Property {property_key} not found in config")
        return None
    
    pms = property_config.get('pms', 'cloudbeds')
    listings = property_config.get('listings', [])
    property_name = property_config.get('name', property_key)
    
    print(f"🔍 Generating pl_daily data for {property_name} ({property_key}) - BATCH MODE")
    print(f"📅 Date range: {start_date} to {end_date}")
    print(f"🏢 PMS: {pms}")
    print(f"🏠 Listings: {len(listings)} (processing in 4 batches of 6)")
    print("=" * 60)
    
    property_start = time.time()
    
    # Get all reservations (will be filtered by listing ID later)
    t0 = time.time()
    all_reservations = fetch_all_reservations(pms, start_date, end_date)
    reservations_time = time.time() - t0
    print(f"📊 Found {len(all_reservations)} total reservations from {pms} (fetched in {reservations_time:.2f}s)\n")
    
    # Split listings into 4 batches of 6 each
    batch_size = 6
    batches = [listings[i:i + batch_size] for i in range(0, len(listings), batch_size)]
    
    all_records = []
    failed_batches = []
    
    # Process each batch
    for batch_num, batch_listings in enumerate(batches, 1):
        print(f"📦 Batch {batch_num}/4: Processing listings {((batch_num-1)*batch_size)+1}-{min(batch_num*batch_size, len(listings))}...")
        batch_start = time.time()
        
        batch_records = []
        batch_failed_listings = []
        
        # Process listings in current batch with parallel processing
        with ThreadPoolExecutor(max_workers=3) as executor:
            # Submit all listing tasks for this batch
            future_to_listing = {
                executor.submit(fetch_listing_data, listing, start_date, end_date, all_reservations, pms): listing 
                for listing in batch_listings
            }
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_listing):
                listing = future_to_listing[future]
                try:
                    # Add delay between listings to respect rate limits
                    time.sleep(2.5)
                    
                    listing_records = future.result()
                    batch_records.extend(listing_records)
                    listing_time = time.time() - batch_start
                    print(f"  ✅ {listing.get('name', 'Unknown')} processed in {listing_time:.2f}s")
                except Exception as exc:
                    print(f"  ❌ {listing.get('name', 'Unknown')} generated an exception: {exc}")
                    batch_failed_listings.append(listing)
        
        # Check if batch was successful
        if batch_failed_listings:
            print(f"  ⚠️  Batch {batch_num} had {len(batch_failed_listings)} failures")
            failed_batches.append((batch_num, batch_failed_listings))
        else:
            print(f"  ✅ Batch {batch_num} completed successfully")
        
        all_records.extend(batch_records)
        batch_time = time.time() - batch_start
        print(f"  📊 Batch {batch_num} processed in {batch_time:.2f}s")
        
        # Wait between batches (except for the last one)
        if batch_num < len(batches):
            print(f"⏳ Waiting 75s before next batch...")
            time.sleep(75)
    
    # Retry failed batches once
    if failed_batches:
        print(f"\n🔄 Retrying {len(failed_batches)} failed batches with longer delays...")
        for batch_num, failed_listings in failed_batches:
            print(f"🔄 Retrying Batch {batch_num}...")
            retry_start = time.time()
            
            # Wait longer before retry
            time.sleep(120)
            
            retry_records = []
            for listing in failed_listings:
                try:
                    time.sleep(5)  # Longer delay for retries
                    listing_records = fetch_listing_data(listing, start_date, end_date, all_reservations, pms)
                    retry_records.extend(listing_records)
                    print(f"  ✅ {listing.get('name', 'Unknown')} retry successful")
                except Exception as exc:
                    print(f"  ❌ {listing.get('name', 'Unknown')} retry failed: {exc}")
            
            all_records.extend(retry_records)
            retry_time = time.time() - retry_start
            print(f"  📊 Batch {batch_num} retry completed in {retry_time:.2f}s")
    
    property_time = time.time() - property_start
    print(f"\n✅ Generated {len(all_records)} total pl_daily records (property processed in {property_time:.2f}s)")
    
    return all_records

def save_pl_daily_csv(pl_daily_data, property_key, output_dir=None):
    """Save pl_daily data to CSV file in the data directory."""
    if not pl_daily_data:
        print("❌ No data to save")
        return
    
    # Convert to DataFrame
    df = pd.DataFrame(pl_daily_data)
    # Ensure correct column order
    columns = [
        'Listing ID', 'PMS Name', 'Date', 'Units', 'No. Booked', 'No. Blocked',
        'blocking_units', 'Bookable Units', 'nightly_revenue', 'Vacant Units'
    ]
    df = df[columns]
    
    # Determine output directory - use data/{property_key} if not specified
    if output_dir is None:
        output_dir = f"data/{property_key}"
    
    # Create output directory if it doesn't exist
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    # Use the standard naming convention: pl_daily_{property_key}.csv
    filename = f"pl_daily_{property_key}.csv"
    
    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath, index=False)
    print(f"💾 Saved pl_daily data to: {filepath}")
    
    return filepath

def test_property(property_key, start_date=None, end_date=None):
    """Test pl_daily generation for a specific property."""
    from utils.date_manager import get_bulk_processing_range
    
    # If no dates provided, use centralized bulk processing range
    if start_date is None or end_date is None:
        start_date_obj, end_date_obj = get_bulk_processing_range()
        start_date = start_date_obj.strftime("%Y-%m-%d")
        end_date = end_date_obj.strftime("%Y-%m-%d")
    
    print(f"🧪 Testing pl_daily generation for {property_key}")
    print(f"📅 Date range: {start_date} to {end_date}")
    print("=" * 60)
    
    # Generate pl_daily data - use batch processing for onera property
    if property_key == 'onera':
        pl_daily_data = generate_pl_daily_for_property_batched(property_key, start_date, end_date)
    else:
        pl_daily_data = generate_pl_daily_for_property(property_key, start_date, end_date)
    
    if pl_daily_data:
        # Save to CSV
        filepath = save_pl_daily_csv(pl_daily_data, property_key)
        
        # Show sample data
        print(f"\n📊 Sample pl_daily data for {property_key}:")
        df = pd.DataFrame(pl_daily_data)
        print(df.head(10).to_string(index=False))
        
        return filepath
    else:
        print(f"❌ Failed to generate pl_daily data for {property_key}")
        return None

if __name__ == "__main__":
    import sys
    
    # Default date range - will use centralized bulk processing range
    default_start_date = None
    default_end_date = None
    
    # Check if property key is provided as command line argument
    if len(sys.argv) > 1:
        property_key = sys.argv[1]
        
        # Check if start_date and end_date are provided
        if len(sys.argv) >= 4:
            start_date = sys.argv[2]
            end_date = sys.argv[3]
            print(f"🧪 Testing pl_daily generation for {property_key}")
            print(f"📅 Date range: {start_date} to {end_date}")
            print("=" * 60)
            test_property(property_key, start_date, end_date)
        else:
            # Use centralized bulk processing range
            from utils.date_manager import get_bulk_processing_range
            start_date_obj, end_date_obj = get_bulk_processing_range()
            dynamic_start_date = start_date_obj.strftime("%Y-%m-%d")
            dynamic_end_date = end_date_obj.strftime("%Y-%m-%d")
            
            print(f"🧪 Testing pl_daily generation for {property_key}")
            print(f"📅 Date range: {dynamic_start_date} to {dynamic_end_date}")
            print("=" * 60)
            test_property(property_key, dynamic_start_date, dynamic_end_date)
    else:
        # Test with all properties for the full range if no argument provided
        import yaml
        with open('config/properties.yaml', 'r') as f:
            config = yaml.safe_load(f)
        all_properties = list(config['properties'].keys())
        
        # Use centralized bulk processing range
        from utils.date_manager import get_bulk_processing_range
        start_date_obj, end_date_obj = get_bulk_processing_range()
        dynamic_start_date = start_date_obj.strftime("%Y-%m-%d")
        dynamic_end_date = end_date_obj.strftime("%Y-%m-%d")
        
        for property_key in all_properties:
            print(f"\n{'='*80}")
            print(f"🧪 Testing pl_daily generation for {property_key}")
            print(f"📅 Date range: {dynamic_start_date} to {dynamic_end_date}")
            print("=" * 60)
            test_property(property_key, dynamic_start_date, dynamic_end_date)
            print(f"{'='*80}\n") 