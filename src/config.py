"""
Configuration management for Temperature Control System.

Loads settings from environment variables (.env file).
All configuration values are defined and validated here.
"""
import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# =============================================================================
# Home Assistant Configuration
# =============================================================================
HA_URL = os.getenv("HA_URL", "https://ha.ketunmetsa.fi")
HA_API_TOKEN = os.getenv("HA_API_TOKEN")

if not HA_API_TOKEN:
    raise ValueError("HA_API_TOKEN environment variable is required")

# Headers for HA API authentication
HA_HEADERS = {
    "Authorization": f"Bearer {HA_API_TOKEN}",
    "Content-Type": "application/json",
}

# =============================================================================
# Sensor Entity IDs
# =============================================================================
TEMPERATURE_SENSOR = os.getenv("TEMPERATURE_SENSOR")  # Indoor temperature sensor (required)
OUTDOOR_TEMP_SENSOR = os.getenv("OUTDOOR_TEMP_SENSOR", "")  # Outdoor temperature (optional)

if not TEMPERATURE_SENSOR:
    raise ValueError("TEMPERATURE_SENSOR environment variable is required")

# =============================================================================
# Switch Entity IDs
# =============================================================================
SWITCH_ENTITY = os.getenv("SWITCH_ENTITY", "switch.shelly1minig3_5432044efb74")  # Room heater switch
CENTRAL_HEATING_SHUTOFF_SWITCH = os.getenv("CENTRAL_HEATING_SHUTOFF_SWITCH")  # Central heating control (optional)

# =============================================================================
# Input/Output Entities
# =============================================================================
BASE_TEMPERATURE_INPUT = os.getenv("BASE_TEMPERATURE_INPUT")  # Optional input_number for base temp
SETPOINT_OUTPUT = os.getenv("SETPOINT_OUTPUT")  # Optional sensor to publish setpoint

# =============================================================================
# Price API Configuration
# =============================================================================
PRICE_SENSOR = os.getenv("PRICE_SENSOR", "sensor.nordpool_kwh_fi_eur_3_10_0255")  # DEPRECATED
SPOT_HINTA_API_JUSTNOW = os.getenv("SPOT_HINTA_API_JUSTNOW", "https://api.spot-hinta.fi/JustNow")
SPOT_HINTA_API_URL = os.getenv("SPOT_HINTA_API_URL", "https://api.spot-hinta.fi/TodayAndDayForward")
ELECTRICITY_VAT_MULTIPLIER = float(os.getenv("ELECTRICITY_VAT_MULTIPLIER", "1.255"))  # 25.5% VAT in Finland

# =============================================================================
# Temperature Control Settings
# =============================================================================
BASE_TEMPERATURE_FALLBACK = float(os.getenv("BASE_TEMPERATURE", "21.0"))
PRICE_LOW_THRESHOLD = float(os.getenv("PRICE_LOW_THRESHOLD", "10.0"))  # Price at which adjustment = 0
PRICE_HIGH_THRESHOLD = float(os.getenv("PRICE_HIGH_THRESHOLD", "20.0"))  # Price at which adjustment = -TEMP_VARIATION
TEMP_VARIATION = float(os.getenv("TEMP_VARIATION", "0.5"))  # Max temperature adjustment (±°C)

# =============================================================================
# Central Heating Control Settings
# =============================================================================
MAX_SHUTOFF_HOURS = float(os.getenv("MAX_SHUTOFF_HOURS", "6.0"))  # Max hours per day to block heating
PRICE_ALWAYS_ON_THRESHOLD = float(os.getenv("PRICE_ALWAYS_ON_THRESHOLD", "5.0"))  # Below this, always heat

# =============================================================================
# External Integrations
# =============================================================================
HEALTHCHECK_URL = os.getenv("HEALTHCHECK_URL")  # Optional healthcheck ping URL

# Price-adjusted thermostats - sends temperature from HA sensor to Shelly TRV
# Bathroom radiator thermostat
BATHROOM_TEMP_SENSOR = os.getenv("BATHROOM_TEMP_SENSOR", "")  # e.g., sensor.ruuvitag_ace9_temperature
BATHROOM_THERMOSTAT_URL = os.getenv("BATHROOM_THERMOSTAT_URL", "")  # e.g., http://192.168.86.32/ext_t?temp=

# KHH radiator thermostat
KHH_TEMP_SENSOR = os.getenv("KHH_TEMP_SENSOR", "")  # e.g., sensor.kodari_sbht_203c_25b4_temperature
KHH_THERMOSTAT_URL = os.getenv("KHH_THERMOSTAT_URL", "")  # e.g., http://192.168.86.31/ext_t?temp=

# =============================================================================
# Timezone
# =============================================================================
TIMEZONE = os.getenv("TZ", "Europe/Helsinki")
