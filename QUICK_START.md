# Quick Start Guide

## Running the Tool

### Option 1: Streamlit UI (Easiest)

```bash
source venv/bin/activate
streamlit run low_occupancy_ui.py
```

Then open **http://localhost:8510** in your browser (default port is set in `.streamlit/config.toml` so it does not use 8501). Override with `streamlit run low_occupancy_ui.py --server.port 8720` if 8510 is taken.

### Option 2: Command Line

```bash
python export_low_occupancy_dates.py \
  --properties onera wb1 \
  --lookahead-days 60 \
  --output results.csv
```

## Common Use Cases

### Find low occupancy dates for specific properties

**UI**: Select properties from dropdown, set booking window, click "Run scan"

**CLI**:
```bash
python export_low_occupancy_dates.py \
  # --properties onera wb1 azulik1 \
  --properties onera wb1 \
  --lookahead-days 90
```

### Use custom threshold

**UI**: Select "manual" threshold mode, enter desired percentage (e.g., 25%)

**CLI**:
```bash
python export_low_occupancy_dates.py \
  --properties onera \
  --threshold-mode manual \
  --manual-threshold 25
```

### Skip data pull (use existing data)

**UI**: Check "Skip pulling pl_daily" checkbox

**CLI**:
```bash
python export_low_occupancy_dates.py \
  --properties onera wb1 \
  --no-fresh-data
```

### Force fresh data pull

**UI**: Check "Force fresh pl_daily pull" checkbox

**CLI**:
```bash
python export_low_occupancy_dates.py \
  --properties onera wb1 \
  --force-fresh-pull
```

## Understanding the Output

### Per-Day Summary
Shows each qualifying date with:
- Occupancy percentage
- Number of listings
- Average rates

### Date Sets
Groups consecutive low-occupancy dates showing:
- Date range (or single date)
- Number of days
- Average occupancy

## Special Notes

<!-- - **azulik1**: Automatically uses Sun-Thu filtering and May onwards dates -->
- **Auto threshold**: Starts at 30%, falls back to 40% if needed
- **Data freshness**: Skips pull if data is less than 5 hours old (unless forced)

## Troubleshooting

**No qualifying dates found**:
- Try increasing the booking window
- Lower the threshold (manual mode)
- Check that pl_daily data exists for selected properties

**Data is outdated**:
- Use "Force fresh pl_daily pull" option
- Or run `generate_all_properties.py` first

**Missing properties**:
- Ensure properties are configured in `config/properties.yaml`
- Check that pl_daily data exists in `data/{property}/` directories
