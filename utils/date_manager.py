"""
Centralized Date Range Management System
Handles all date range calculations and validations throughout the pricing tool
"""

import yaml
import logging
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Tuple, Optional, Dict, Any
import calendar

logger = logging.getLogger(__name__)

class DateRangeManager:
    """Centralized date range management for the pricing tool"""
    
    def __init__(self, config_path: str = "config/date_ranges.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.current_year = self.config.get('current_year', datetime.now().year)
        
    def _load_config(self) -> Dict[str, Any]:
        """Load date range configuration from YAML file"""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"Loaded date range configuration from {self.config_path}")
            return config
        except FileNotFoundError:
            logger.error(f"Date range config not found at {self.config_path}")
            return self._get_default_config()
        except yaml.YAMLError as e:
            logger.error(f"Error parsing date range config: {e}")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration if file is missing"""
        return {
            'current_year': datetime.now().year,
            'data_generation': {
                'full_start_date': f"{datetime.now().year}-01-01",
                'full_end_date': f"{datetime.now().year}-12-31",
                'operational_start_date': f"{datetime.now().year}-01-01",
                'operational_end_date': f"{datetime.now().year}-12-31",
                'ui_default_start_date': f"{datetime.now().year}-05-20",
                'ui_default_end_date': f"{datetime.now().year}-07-28"
            },
            'dynamic_calculations': {
                'scheduler_start_offset_months': -1,
                'scheduler_end_offset_months': 0,
                'nightly_pull_days_ahead': 365,
                'bulk_processing_days_back': 30,
                'bulk_processing_end_offset_months': 0
            }
        }
    
    def get_full_calculation_range(self) -> Tuple[date, date]:
        """Get the full date range for comprehensive rate calculations"""
        config = self.config['data_generation']
        start_date = datetime.strptime(config['full_start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(config['full_end_date'], '%Y-%m-%d').date()
        return start_date, end_date
    
    def get_operational_range(self) -> Tuple[date, date]:
        """Get the operational date range for daily operations"""
        config = self.config['data_generation']
        start_date = datetime.strptime(config['operational_start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(config['operational_end_date'], '%Y-%m-%d').date()
        return start_date, end_date
    
    def get_ui_default_range(self) -> Tuple[date, date]:
        """Get the default date range for user interface"""
        config = self.config['data_generation']
        start_date = datetime.strptime(config['ui_default_start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(config['ui_default_end_date'], '%Y-%m-%d').date()
        return start_date, end_date
    
    def get_scheduler_dynamic_range(self) -> Tuple[date, date]:
        """Calculate dynamic date range for scheduler: last month to end of current year"""
        today = datetime.now()
        config = self.config['dynamic_calculations']
        
        # Calculate start date (first day of last month)
        start_offset = config['scheduler_start_offset_months']
        if today.month + start_offset <= 0:
            start_year = today.year - 1
            start_month = 12 + (today.month + start_offset)
        else:
            start_year = today.year
            start_month = today.month + start_offset
        
        start_date = date(start_year, start_month, 1)
        
        # Calculate end date (last day of current year + offset)
        end_offset = config['scheduler_end_offset_months']
        if today.month + end_offset <= 0:
            end_year = today.year - 1
            end_month = 12 + (today.month + end_offset)
        else:
            end_year = today.year
            end_month = today.month + end_offset
        
        # Get last day of the month
        last_day = calendar.monthrange(end_year, end_month)[1]
        end_date = date(end_year, end_month, last_day)
        
        return start_date, end_date
    
    def get_nightly_pull_range(self) -> Tuple[date, date]:
        """Calculate date range for nightly pull: today to +N days, or same start as bulk processing if enabled"""
        config = self.config['dynamic_calculations']
        days_ahead = config['nightly_pull_days_ahead']
        
        # Check if we should use the same start date as bulk processing
        if config.get('nightly_pull_use_bulk_start', False):
            # Use same start date as bulk processing
            bulk_start, _ = self.get_bulk_processing_range()
            end_date = bulk_start + timedelta(days=days_ahead)
            return bulk_start, end_date
        else:
            # Use today as start date (original behavior)
            today = date.today()
            end_date = today + timedelta(days=days_ahead)
            return today, end_date
    
    def get_bulk_processing_range(self) -> Tuple[date, date]:
        """Calculate date range for bulk processing: N days ago to end of current year"""
        today = datetime.now()
        config = self.config['dynamic_calculations']
        
        # Start date: N days ago
        days_back = config['bulk_processing_days_back']
        start_date = today - timedelta(days=days_back)
        start_date = start_date.date()
        
        # End date: end of current year + offset
        end_offset = config['bulk_processing_end_offset_months']
        if end_offset == 0:
            # End of current year
            end_year = today.year
            end_month = 12
        elif today.month + end_offset <= 0:
            # Past year
            end_year = today.year - 1
            end_month = 12 + (today.month + end_offset)
        else:
            # Future months - handle year overflow
            total_months = today.month + end_offset
            end_year = today.year + (total_months - 1) // 12
            end_month = ((total_months - 1) % 12) + 1
        
        # Get last day of the month
        last_day = calendar.monthrange(end_year, end_month)[1]
        end_date = date(end_year, end_month, last_day)
        
        return start_date, end_date
    
    def get_api_default_range(self) -> Tuple[date, date]:
        """Get default date range for API operations"""
        config = self.config['api_operations']
        start_date = datetime.strptime(config['default_start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(config['default_end_date'], '%Y-%m-%d').date()
        return start_date, end_date
    
    def validate_date_range(self, start_date: date, end_date: date) -> Tuple[bool, str]:
        """Validate a date range against configured rules"""
        config = self.config.get('validation', {})
        
        # Check if start date is before end date
        if start_date > end_date:
            return False, "Start date cannot be after end date"
        
        # Check minimum range
        min_days = config.get('min_range_days', 1)
        if (end_date - start_date).days < min_days:
            return False, f"Date range must be at least {min_days} days"
        
        # Check maximum range
        max_days = config.get('max_range_days', 1095)
        if (end_date - start_date).days > max_days:
            return False, f"Date range cannot exceed {max_days} days"
        
        # Check future date limit
        max_future_days = config.get('max_future_days', 730)
        today = date.today()
        if end_date > today + timedelta(days=max_future_days):
            return False, f"End date cannot be more than {max_future_days} days in the future"
        
        return True, "Valid date range"
    
    def format_date_range(self, start_date: date, end_date: date) -> str:
        """Format date range as string for display"""
        return f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
    
    def get_date_range_info(self) -> Dict[str, Any]:
        """Get comprehensive information about all configured date ranges"""
        return {
            'full_calculation_range': self.format_date_range(*self.get_full_calculation_range()),
            'operational_range': self.format_date_range(*self.get_operational_range()),
            'ui_default_range': self.format_date_range(*self.get_ui_default_range()),
            'scheduler_dynamic_range': self.format_date_range(*self.get_scheduler_dynamic_range()),
            'nightly_pull_range': self.format_date_range(*self.get_nightly_pull_range()),
            'bulk_processing_range': self.format_date_range(*self.get_bulk_processing_range()),
            'api_default_range': self.format_date_range(*self.get_api_default_range()),
            'current_year': self.current_year,
            'config_file': str(self.config_path)
        }

# Global instance for easy access
date_manager = DateRangeManager()

# Convenience functions for backward compatibility
def get_full_calculation_range() -> Tuple[date, date]:
    """Get full calculation date range"""
    return date_manager.get_full_calculation_range()

def get_operational_range() -> Tuple[date, date]:
    """Get operational date range"""
    return date_manager.get_operational_range()

def get_ui_default_range() -> Tuple[date, date]:
    """Get UI default date range"""
    return date_manager.get_ui_default_range()

def get_scheduler_dynamic_range() -> Tuple[date, date]:
    """Get scheduler dynamic date range"""
    return date_manager.get_scheduler_dynamic_range()

def get_nightly_pull_range() -> Tuple[date, date]:
    """Get nightly pull date range"""
    return date_manager.get_nightly_pull_range()

def get_bulk_processing_range() -> Tuple[date, date]:
    """Get bulk processing date range"""
    return date_manager.get_bulk_processing_range()

def validate_date_range(start_date: date, end_date: date) -> Tuple[bool, str]:
    """Validate date range"""
    return date_manager.validate_date_range(start_date, end_date)

def get_date_range_info() -> Dict[str, Any]:
    """Get all date range information"""
    return date_manager.get_date_range_info()
