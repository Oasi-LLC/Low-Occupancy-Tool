# Low Occupancy Tool - Standalone Package

## ✅ Complete & Self-Contained

This package contains **everything** you need to run the Low Occupancy Accelerator Dates tool in a new project, with **zero dependencies** on the original pricing_tool project.

## 📦 What's Included

### Core Tool
- `low_occupancy_ui.py` - Streamlit web interface
- `export_low_occupancy_dates.py` - Core analysis engine

### Data Generation
- `generate_pl_daily_comprehensive.py` - Pulls data from PriceLabs API

### All Dependencies
- `utils/backend_interface.py` - Property listing and rate generation
- `utils/date_manager.py` - Date range management
- `rates/config.py` - API configuration
- `rates/logging_setup.py` - Logging utilities
- `src/pricing_engine/` - Complete pricing calculation engine
  - `calculator.py` - Rate calculations
  - `dataloader.py` - Data loading
  - `utils.py` - Date utilities

### Configuration
- `config/properties.yaml` - Property configurations (edit for your properties)
- `config/date_ranges.yaml` - Date range settings (edit as needed)

### Setup Files
- `requirements.txt` - All Python dependencies
- `.env.example` - Environment variable template (copy to `.env` and add your API key)

### Documentation
- `README.md` - This file - complete documentation
- `QUICK_START.md` - Quick reference guide

## 🚀 Quick Start

1. **Copy this entire folder** to your new project location

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment:**
   ```bash
   cp .env.example .env
   # Edit .env and add your PRICELABS_API_KEY
   ```

4. **Configure properties:**
   - Edit `config/properties.yaml` with your property details
   - Edit `config/date_ranges.yaml` if needed

5. **Generate data files:**
   
   Generate pl_daily data for a single property:
   ```bash
   python generate_pl_daily_comprehensive.py onera
   ```
   
   Or generate for all properties at once:
   ```bash
   python generate_all_properties.py
   ```
   
   This will create `data/{property}/pl_daily_{property}.csv` files.

6. **Run the tool:**
   ```bash
   streamlit run low_occupancy_ui.py
   ```

## 📁 Directory Structure

```
standalone_package/
├── low_occupancy_ui.py          # Main UI
├── export_low_occupancy_dates.py # Core logic
├── generate_pl_daily_comprehensive.py # Data generator
├── requirements.txt
├── .env.example
├── .gitignore
├── config/
│   ├── properties.yaml          # Edit this!
│   └── date_ranges.yaml          # Edit this!
├── data/                         # Create subdirs per property
│   └── {property_name}/
│       └── pl_daily_{property_name}.csv
├── utils/
│   ├── backend_interface.py
│   └── date_manager.py
├── rates/
│   ├── config.py
│   └── logging_setup.py
└── src/
    └── pricing_engine/
        ├── __init__.py
        ├── calculator.py
        ├── dataloader.py
        └── utils.py
```

## ✨ Features

- **Self-contained** - No external dependencies
- **Complete** - All scripts and utilities included
- **Ready to use** - Just configure and run
- **Well documented** - Multiple guides included

## 📝 Notes

- You'll need a PriceLabs API key (set in `.env`)
- Property configurations must match your PriceLabs account
- Data files (`pl_daily_*.csv`) must be generated first
- The tool works independently of the original pricing_tool project

## 🆘 Need Help?

- See `QUICK_START.md` for quick reference
- Check the code comments for detailed explanations
- Ensure your `.env` file has a valid `PRICELABS_API_KEY`

## ⚠️ Important Notes

- **API Key Required**: You must have a valid PriceLabs API key
- **Data Files**: Generate `pl_daily` CSV files for each property before using the tool
- **Rate Limits**: The API has rate limits; if generation fails, wait and retry
- **Security**: Never commit your `.env` file (it's in `.gitignore`)

## 📄 License

[Add your license here - MIT, Apache, etc.]
