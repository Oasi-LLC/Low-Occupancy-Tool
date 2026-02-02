import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Configuration
API_KEY = os.getenv('PRICELABS_API_KEY')
BASE_URL = os.getenv('API_BASE_URL', 'https://api.pricelabs.co/v1')

# Validation
if not API_KEY:
    raise ValueError("PRICELABS_API_KEY environment variable is required")

# Price Adjustment Configuration
ADJUSTMENT_PERCENTAGE = 5  # 5% adjustment
DEFAULT_CURRENCY = "USD"
DEFAULT_PMS = "cloudbeds"

# API Rate Limiting
MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds

# Logging Configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# File Paths
DATA_DIR = "data/changes" 