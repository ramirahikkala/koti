"""
Temperature Control System - Main Control Logic.

This module contains the main control cycle that:
1. Reads current temperature and price
2. Calculates target setpoint
3. Controls room heater and central heating
4. Updates bathroom thermostat with price-adjusted temperature
"""
import logging

from .config import (
    TEMPERATURE_SENSOR,
    PRICE_SENSOR,
    CENTRAL_HEATING_SHUTOFF_SWITCH,
    MAX_SHUTOFF_HOURS,
    PRICE_ALWAYS_ON_THRESHOLD,
    BATHROOM_THERMOSTAT_URL,
)
from .ha_client import (
    get_base_temperature,
    get_current_price,
    get_current_temperature,
    get_daily_prices,
    control_heating,
    control_central_heating,
    update_setpoint_in_ha,
    ping_healthcheck,
)
from .temperature_logic import (
    get_setpoint_temperature,
    should_central_heating_run,
    log_heating_decision,
)
from .background_tasks import send_temperature_to_bathroom_thermostat

logger = logging.getLogger(__name__)


def run_control():
    """Execute one temperature control cycle."""
    logger.info("=" * 60)
    logger.info("Electricity Price-Based Temperature Control System")
    logger.info("=" * 60)

    # Get base temperature
    logger.info("Fetching base temperature setpoint...")
    base_temperature = get_base_temperature()

    # Get current electricity price
    logger.info(f"Fetching current electricity price from {PRICE_SENSOR}...")
    current_price = get_current_price()

    # Get current temperature
    logger.info(f"Fetching current temperature from {TEMPERATURE_SENSOR}...")
    current_temperature = get_current_temperature()

    if current_price is not None and current_temperature is not None:
        logger.info(f"Current electricity price: {current_price} c/kWh")
        logger.info(f"Current temperature: {current_temperature}°C")
        
        # Calculate target temperature
        setpoint_temp, adjustment = get_setpoint_temperature(current_price, base_temperature)
        
        logger.info("Temperature Calculation:")
        logger.info(f"  Base temperature: {base_temperature}°C")
        logger.info(f"  Price adjustment: {adjustment:+.2f}°C")
        logger.info(f"  → Target setpoint: {setpoint_temp}°C")
        
        # Update setpoint in HA
        update_setpoint_in_ha(setpoint_temp)
        
        # Decision logic: heat if current temperature is below target setpoint
        should_heat = current_temperature < setpoint_temp
        temp_diff = setpoint_temp - current_temperature
        
        logger.info("Control Decision:")
        logger.info(f"  Current: {current_temperature}°C")
        logger.info(f"  Target:  {setpoint_temp}°C")
        logger.info(f"  Difference: {temp_diff:+.2f}°C")
        if should_heat:
            logger.info("  → HEAT ON (current < target)")
        else:
            logger.info("  → HEAT OFF (current ≥ target)")
        
        # Apply control
        logger.info("Applying room temperature control...")
        control_heating(should_heat)
        
        logger.info("=" * 60)
        logger.info("Room temperature control executed successfully!")
        logger.info("=" * 60)
        
        # Central heating control (if configured)
        if CENTRAL_HEATING_SHUTOFF_SWITCH:
            logger.info("")
            logger.info("=" * 60)
            logger.info("Central Heating Control")
            logger.info("=" * 60)
            
            # Get all daily prices for ranking
            logger.info("Fetching daily price data for ranking...")
            daily_prices = get_daily_prices()
            
            if daily_prices:
                logger.info(f"Retrieved {len(daily_prices)} quarter-hourly prices")
                logger.info(f"Price range: {min(daily_prices):.2f} - {max(daily_prices):.2f} c/kWh")
                logger.info(f"Configuration: Max {MAX_SHUTOFF_HOURS}h shutoff, Always-on threshold: {PRICE_ALWAYS_ON_THRESHOLD:.2f} c/kWh")

                # If room heater is on, always keep central heating on
                if should_heat:
                    should_run = True
                    reason = "Room heater is ON - central heating forced ON"
                else:
                    # Determine if central heating should run based on price ranking
                    should_run, reason = should_central_heating_run(current_price, daily_prices)
                
                # Log decision to Home Assistant for easy filtering
                log_heating_decision(should_run, reason, current_price)
                
                logger.info("Central Heating Decision:")
                logger.info(f"  Current price: {current_price:.2f} c/kWh")
                logger.info(f"  Reason: {reason}")
                if should_run:
                    logger.info("  → CENTRAL HEATING RUNNING (control switch will be OFF)")
                else:
                    logger.info("  → CENTRAL HEATING BLOCKED (control switch will be ON - shutoff during expensive period)")
                
                # Apply central heating control
                logger.info("Applying central heating control...")
                control_central_heating(should_run)
                
                logger.info("=" * 60)
                logger.info("Central heating control executed successfully!")
                logger.info("=" * 60)
            else:
                logger.warning("Could not retrieve daily prices for central heating control")
                logger.info("=" * 60)
        
        # Bathroom thermostat control (if configured)
        if BATHROOM_THERMOSTAT_URL:
            logger.info("")
            logger.info("=" * 60)
            logger.info("Bathroom Thermostat Control")
            logger.info("=" * 60)
            send_temperature_to_bathroom_thermostat()
            logger.info("=" * 60)
        
        # Ping healthcheck to indicate successful completion
        ping_healthcheck(success=True)
        
    else:
        if current_price is None:
            logger.error("Failed to get electricity price.")
        if current_temperature is None:
            logger.error("Failed to get current temperature.")
        logger.error("Aborting temperature control.")
        logger.info("=" * 60)
        
        # Ping healthcheck with failure status
        ping_healthcheck(success=False)
