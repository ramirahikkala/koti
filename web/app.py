"""
Web GUI for Temperature Control System.

Provides REST API endpoints and serves the web dashboard.
"""
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from flask_caching import Cache
import threading
import time
import os
from datetime import datetime, timedelta, timezone
import requests
import pytz

# Import from refactored modules (src package)
from src.config import (
    HA_URL,
    HA_HEADERS,
    TEMPERATURE_SENSOR,
    OUTDOOR_TEMP_SENSOR,
    SWITCH_ENTITY,
    CENTRAL_HEATING_SHUTOFF_SWITCH,
    BASE_TEMPERATURE_FALLBACK,
    BASE_TEMPERATURE_INPUT,
    MAX_SHUTOFF_HOURS,
    PRICE_ALWAYS_ON_THRESHOLD,
    PRICE_LOW_THRESHOLD,
    PRICE_HIGH_THRESHOLD,
    TEMP_VARIATION,
    SETPOINT_OUTPUT,
    BATHROOM_TEMP_SENSOR,
    BATHROOM_THERMOSTAT_URL,
    KHH_TEMP_SENSOR,
    KHH_THERMOSTAT_URL,
    ELECTRICITY_VAT_MULTIPLIER,
)
from src.ha_client import (
    get_base_temperature,
    get_current_price,
    get_current_temperature,
    get_outdoor_temperature,
    get_daily_prices,
    get_tomorrow_prices,
    get_room_heater_state,
    get_central_heating_state,
)
from src.temperature_logic import (
    get_setpoint_temperature,
    should_central_heating_run,
)
from src.control import run_control
from src.background_tasks import get_sensor_temperature, calculate_price_adjusted_temperature
from src.heating_logger import get_decisions, get_decisions_by_date
from src.background_tasks import (
    warm_cache,
    get_bathroom_raw_temperature,
    calculate_bathroom_adjusted_temperature,
)


# =============================================================================
# Flask Application Setup
# =============================================================================

# Get the directory where this file is located
_web_dir = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, template_folder=os.path.join(_web_dir, 'templates'))
CORS(app)  # Enable CORS for API endpoints

# Initialize caching with 15-minute timeout for history data
# Using 'simple' in-memory cache (adequate with single gunicorn worker)
cache = Cache(app, config={'CACHE_TYPE': 'simple', 'CACHE_DEFAULT_TIMEOUT': 900})

# Track if background tasks have been started (to prevent multiple instances)
_cache_warmer_started = False


# =============================================================================
# Background Task Starters
# =============================================================================

def start_cache_warmer_once():
    """Start cache warmer only once, even if module is loaded multiple times."""
    global _cache_warmer_started
    if not _cache_warmer_started:
        # Only warm endpoints that are actually cached (history data)
        # Current state/price endpoints are NOT cached - always fresh
        endpoints_to_warm = [
            '/api/history?hours=24',
            f'/api/switch-history?entity_id={SWITCH_ENTITY}&hours=24' if SWITCH_ENTITY else None,
            '/api/heating-decisions?limit=20',
        ]
        # Filter out None values
        endpoints_to_warm = [e for e in endpoints_to_warm if e]
        
        thread = threading.Thread(target=warm_cache, args=(app, endpoints_to_warm), daemon=True)
        thread.start()
        _cache_warmer_started = True


# =============================================================================
# Helper Functions
# =============================================================================

def _get_thermostat_status(sensor_id: str, thermostat_url: str, thermostat_name: str, current_price: float):
    """Get thermostat status for API response.
    
    Args:
        sensor_id: HA sensor entity ID
        thermostat_url: Shelly TRV URL
        thermostat_name: Human-readable name
        current_price: Current electricity price in c/kWh
    
    Returns:
        dict with raw_temp, adjustment, adjusted_temp, configured, sensor, url
    """
    if not thermostat_url or not sensor_id:
        return {
            "configured": False,
            "sensor": sensor_id,
            "url": thermostat_url
        }
    
    raw_temp = get_sensor_temperature(sensor_id, thermostat_name)
    
    if raw_temp is None or current_price is None:
        return {
            "configured": True,
            "raw_temp": raw_temp,
            "adjustment": None,
            "adjusted_temp": None,
            "sensor": sensor_id,
            "url": thermostat_url
        }
    
    adjustment = (current_price - 5) / 5
    # Cap adjustment to ±1°C
    adjustment = max(-1.0, min(1.0, adjustment))
    adjusted_temp = calculate_price_adjusted_temperature(raw_temp, current_price)
    
    return {
        "configured": True,
        "raw_temp": raw_temp,
        "adjustment": adjustment,
        "adjusted_temp": adjusted_temp,
        "sensor": sensor_id,
        "url": thermostat_url
    }


def _get_bathroom_thermostat_status(current_price):
    """Get bathroom thermostat status for API response (deprecated - use _get_thermostat_status)."""
    return _get_thermostat_status(BATHROOM_TEMP_SENSOR, BATHROOM_THERMOSTAT_URL, "bathroom", current_price)


# =============================================================================
# Web Routes
# =============================================================================

@app.route('/')
def index():
    """Render the main dashboard."""
    return render_template('index.html')


# =============================================================================
# API Endpoints
# =============================================================================

@app.route('/api/current-state')
def api_current_state():
    """Get current temperature, price, and setpoint.
    
    Returns: {temperature: float, price: float, setpoint: float, adjustment: float}
    NOT cached - always returns fresh data
    """
    try:
        base_temp = get_base_temperature()
        current_price = get_current_price()
        current_temp = get_current_temperature()
        
        if current_price is None or current_temp is None:
            return jsonify({"error": "Failed to fetch sensor data"}), 500
        
        setpoint_temp, adjustment = get_setpoint_temperature(current_price, base_temp)
        
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "temperature": current_temp,
            "base_temperature": base_temp,
            "price": current_price,
            "setpoint": setpoint_temp,
            "adjustment": adjustment
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/switches-state')
def api_switches_state():
    """Get current state of all switches (room heater, central heating).
    
    Returns: {room_heater: {state, entity_id}, central_heating: {state, is_running, entity_id}}
    NOT cached - always returns fresh data
    """
    try:
        result = {
            "timestamp": datetime.now().isoformat(),
            "switches": {}
        }
        
        # Room heater state
        room_heater = get_room_heater_state()
        if room_heater:
            result["switches"]["room_heater"] = {
                "state": room_heater,
                "entity_id": SWITCH_ENTITY
            }
        
        # Central heating state
        central_heating = get_central_heating_state()
        if central_heating:
            result["switches"]["central_heating"] = {
                **central_heating,
                "entity_id": CENTRAL_HEATING_SHUTOFF_SWITCH
            }
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/prices')
def api_prices():
    """Get electricity prices: today and tomorrow.
    
    Returns: {current: float, daily_prices: [96], tomorrow_prices: [96], daily_min: float, daily_max: float}
    NOT cached - current price must be fresh
    """
    try:
        current_price = get_current_price()
        daily_prices = get_daily_prices()
        tomorrow_prices = get_tomorrow_prices()
        
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "current": current_price,
            "daily_prices": daily_prices,
            "tomorrow_prices": tomorrow_prices,
            "daily_min": min(daily_prices) if daily_prices else None,
            "daily_max": max(daily_prices) if daily_prices else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/central-heating-decision')
def api_central_heating_decision():
    """Get central heating run/block decision logic.
    
    Returns: {should_run: bool, reason: str, current_price: float}
    NOT cached - must reflect current price
    """
    try:
        current_price = get_current_price()
        daily_prices = get_daily_prices()
        
        if not daily_prices or CENTRAL_HEATING_SHUTOFF_SWITCH is None:
            return jsonify({"should_run": None, "reason": "Insufficient data or not configured", "current_price": current_price}), 200
        
        should_run, reason = should_central_heating_run(current_price, daily_prices)
        
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "should_run": should_run,
            "reason": reason,
            "current_price": current_price
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/status')
def api_status():
    """Get combined current status (aggregates all focused endpoints).
    
    This endpoint combines data from multiple focused endpoints for convenience.
    NOT cached - always returns fresh data
    """
    try:
        base_temp = get_base_temperature()
        current_price = get_current_price()
        current_temp = get_current_temperature()
        
        if current_price is None or current_temp is None:
            return jsonify({"error": "Failed to fetch sensor data"}), 500
        
        setpoint_temp, adjustment = get_setpoint_temperature(current_price, base_temp)
        outdoor_temp = get_outdoor_temperature()
        
        # Get switch states
        room_heater_state = get_room_heater_state()
        central_heating = get_central_heating_state()
        
        # Get daily prices and central heating decision
        daily_prices = get_daily_prices()
        tomorrow_prices = get_tomorrow_prices()
        
        central_heating_decision = None
        if daily_prices and CENTRAL_HEATING_SHUTOFF_SWITCH:
            should_run, reason = should_central_heating_run(current_price, daily_prices)
            central_heating_decision = {
                "should_run": should_run,
                "reason": reason
            }
        
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "temperature": {
                "current": current_temp,
                "outdoor": outdoor_temp,
                "base": base_temp,
                "setpoint": setpoint_temp,
                "adjustment": adjustment
            },
            "price": {
                "current": current_price,
                "daily_prices": daily_prices,
                "tomorrow_prices": tomorrow_prices,
                "daily_min": min(daily_prices) if daily_prices else None,
                "daily_max": max(daily_prices) if daily_prices else None
            },
            "switches": {
                "room_heater": {
                    "state": room_heater_state,
                    "entity_id": SWITCH_ENTITY
                },
                "central_heating": {
                    "shutoff_switch_state": central_heating["state"] if central_heating else None,
                    "is_running": central_heating["is_running"] if central_heating else None,
                    "entity_id": CENTRAL_HEATING_SHUTOFF_SWITCH,
                    "decision": central_heating_decision
                }
            },
            "thermostats": {
                "bathroom": _get_thermostat_status(BATHROOM_TEMP_SENSOR, BATHROOM_THERMOSTAT_URL, "bathroom", current_price),
                "khh": _get_thermostat_status(KHH_TEMP_SENSOR, KHH_THERMOSTAT_URL, "KHH", current_price)
            },
            "config": {
                "base_temperature_fallback": BASE_TEMPERATURE_FALLBACK,
                "base_temperature_input": BASE_TEMPERATURE_INPUT,
                "max_shutoff_hours": MAX_SHUTOFF_HOURS,
                "price_always_on_threshold": PRICE_ALWAYS_ON_THRESHOLD,
                "price_low_threshold": PRICE_LOW_THRESHOLD,
                "price_high_threshold": PRICE_HIGH_THRESHOLD,
                "temp_variation": TEMP_VARIATION,
                "setpoint_output": SETPOINT_OUTPUT
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/switch-history-debug')
def api_switch_history_debug():
    """Debug endpoint to show detailed processing of switch history."""
    try:
        entity_id = request.args.get('entity_id')
        hours_str = request.args.get('hours', '24')
        
        if not entity_id:
            return jsonify({"error": "entity_id parameter required"}), 400
        
        try:
            hours = int(hours_str)
        except (ValueError, TypeError):
            hours = 24
        
        local_tz = pytz.timezone('Europe/Helsinki')
        
        # Fetch 72h of history
        now_utc = datetime.now(timezone.utc)
        lookback_hours = max(hours * 2 + 12, 72)
        start_utc = now_utc - timedelta(hours=lookback_hours)
        start_iso = start_utc.replace(tzinfo=None).isoformat()
        end_utc = now_utc + timedelta(hours=1)
        end_iso = end_utc.replace(tzinfo=None).isoformat()
        
        url = f"{HA_URL}/api/history/period/{start_iso}?filter_entity_id={entity_id}&end_time={end_iso}"
        resp = requests.get(url, headers=HA_HEADERS, timeout=60)
        
        if resp.status_code != 200:
            return jsonify({"error": f"HA API returned {resp.status_code}"}), 500
        
        history = resp.json()
        
        # Parse all state changes
        points = []
        raw_points = []
        if history and len(history) > 0 and len(history[0]) > 0:
            for s in history[0]:
                ts_str = s.get('last_changed')
                state = s.get('state')
                raw_points.append({"timestamp": ts_str, "state": state})
                try:
                    dt_utc = datetime.fromisoformat(ts_str)
                    if dt_utc.tzinfo is None:
                        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                    dt_local = dt_utc.astimezone(local_tz)
                    points.append({"ts": dt_local, "state": state})
                except Exception as e:
                    print(f"DEBUG: Error parsing {ts_str}: {e}")
        
        points.sort(key=lambda p: p['ts'])
        
        # Calculate period
        target_date_end = datetime.now(local_tz).replace(microsecond=0)
        target_date_start = target_date_end - timedelta(hours=hours)
        
        # Find initial state
        state_at_period_start = 'off'
        for p in points:
            if p['ts'] <= target_date_start:
                state_at_period_start = p['state']
            else:
                break
        
        # Count state changes in period
        changes_in_period = [p for p in points if target_date_start < p['ts'] <= target_date_end]
        
        return jsonify({
            "entity_id": entity_id,
            "hours": hours,
            "lookback_hours": lookback_hours,
            "period_start": target_date_start.isoformat(),
            "period_end": target_date_end.isoformat(),
            "state_at_period_start": state_at_period_start,
            "total_points": len(points),
            "points_in_period": len(changes_in_period),
            "raw_points": raw_points[-10:],
            "parsed_points": [{"ts": str(p['ts']), "state": p['state']} for p in points[-10:]],
            "changes_in_period": [{"ts": str(p['ts']), "state": p['state']} for p in changes_in_period]
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/switch-history')
@cache.cached(timeout=900, query_string=True)
def api_switch_history():
    """Get switch ON/OFF state for each quarter-hour (0-95) for a given period and entity.
    
    Query parameters:
    - entity_id: Home Assistant entity ID (e.g., switch.central_heating) [REQUIRED]
    - date: YYYY-MM-DD (optional) - specific date to analyze
    - hours: number of hours to look back (optional, default: 24) - if used, date is ignored
    """
    try:
        entity_id = request.args.get('entity_id')
        date_str = request.args.get('date')
        hours_str = request.args.get('hours', '24')
        
        if not entity_id:
            return jsonify({"error": "entity_id parameter required"}), 400
        
        try:
            hours = int(hours_str)
        except (ValueError, TypeError):
            hours = 24
        
        local_tz = pytz.timezone('Europe/Helsinki')
        
        # Fetch history with generous lookback
        now_utc = datetime.now(timezone.utc)
        lookback_hours = max(hours * 2 + 12, 72)
        start_utc = now_utc - timedelta(hours=lookback_hours)
        start_iso = start_utc.replace(tzinfo=None).isoformat()
        end_utc = now_utc + timedelta(hours=1)
        end_iso = end_utc.replace(tzinfo=None).isoformat()
        
        url = f"{HA_URL}/api/history/period/{start_iso}?filter_entity_id={entity_id}&end_time={end_iso}"
        resp = requests.get(url, headers=HA_HEADERS, timeout=60)
        if resp.status_code != 200:
            return jsonify({"error": f"HA API returned {resp.status_code}"}), 500
        
        history = resp.json()
        
        # Parse all state changes and convert to local time
        points = []
        if history and len(history) > 0 and len(history[0]) > 0:
            for s in history[0]:
                ts_str = s.get('last_changed')
                state = s.get('state')
                try:
                    dt_utc = datetime.fromisoformat(ts_str)
                    if dt_utc.tzinfo is None:
                        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                    dt_local = dt_utc.astimezone(local_tz)
                    points.append({"ts": dt_local, "state": state})
                except Exception:
                    continue
        
        points.sort(key=lambda p: p['ts'])
        
        # Determine target period
        if date_str:
            target_date = datetime.fromisoformat(date_str).date()
            target_date_start = local_tz.localize(datetime.combine(target_date, datetime.min.time()))
            target_date_end = local_tz.localize(datetime.combine(target_date, datetime.max.time()))
            mode = "date"
        else:
            target_date_end = datetime.now(local_tz).replace(microsecond=0)
            target_date_start = target_date_end - timedelta(hours=hours)
            mode = "hours"
        
        # Find state at start of period
        state_at_period_start = 'off'
        for p in points:
            if p['ts'] <= target_date_start:
                state_at_period_start = p['state']
            else:
                break
        
        # Initialize all 96 quarters with the starting state
        quarters = [state_at_period_start] * 96
        
        # Apply state changes during the period
        for p in points:
            if not (target_date_start <= p['ts'] <= target_date_end):
                continue
            
            time_into_period = p['ts'] - target_date_start
            minutes_into_period = int(time_into_period.total_seconds() / 60)
            quarter_idx = minutes_into_period // 15
            
            if quarter_idx < 0:
                quarter_idx = 0
            elif quarter_idx >= 96:
                quarter_idx = 95
            
            for i in range(quarter_idx, 96):
                quarters[i] = p['state']
        
        result = {
            "entity_id": entity_id,
            "quarters": quarters,
            "mode": mode
        }
        
        if mode == "date":
            result["date"] = date_str
        else:
            result["hours"] = hours
        
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """Get or update configuration."""
    if request.method == 'GET':
        return jsonify({
            "BASE_TEMPERATURE": BASE_TEMPERATURE_FALLBACK,
            "MAX_SHUTOFF_HOURS": MAX_SHUTOFF_HOURS,
            "PRICE_ALWAYS_ON_THRESHOLD": PRICE_ALWAYS_ON_THRESHOLD,
            "PRICE_LOW_THRESHOLD": PRICE_LOW_THRESHOLD,
            "PRICE_HIGH_THRESHOLD": PRICE_HIGH_THRESHOLD,
            "TEMP_VARIATION": TEMP_VARIATION,
            "TEMPERATURE_SENSOR": TEMPERATURE_SENSOR,
            "OUTDOOR_TEMP_SENSOR": OUTDOOR_TEMP_SENSOR,
            "SWITCH_ENTITY": SWITCH_ENTITY,
            "CENTRAL_HEATING_SHUTOFF_SWITCH": CENTRAL_HEATING_SHUTOFF_SWITCH
        })
    
    elif request.method == 'POST':
        return jsonify({"status": "Configuration update not yet implemented"}), 501


@app.route('/api/trigger', methods=['POST'])
def api_trigger():
    """Manually trigger a control cycle."""
    try:
        run_control()
        return jsonify({"status": "success", "message": "Control cycle executed"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/history')
@cache.cached(timeout=900, query_string=True)
def api_history():
    """Get historical data from Home Assistant (cached for 15 minutes)."""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        hours = int(request.args.get('hours', 24))
        
        now_utc = datetime.now(timezone.utc)
        start_time = now_utc - timedelta(hours=hours)
        start_time_iso = start_time.replace(tzinfo=None).isoformat()
        
        # Build list of entities to query
        entities = []
        if TEMPERATURE_SENSOR:
            entities.append(TEMPERATURE_SENSOR)
        if OUTDOOR_TEMP_SENSOR:
            entities.append(OUTDOOR_TEMP_SENSOR)
        if SWITCH_ENTITY:
            entities.append(SWITCH_ENTITY)
        if CENTRAL_HEATING_SHUTOFF_SWITCH:
            entities.append(CENTRAL_HEATING_SHUTOFF_SWITCH)
        
        # Add Nordpool sensor for historical prices (without VAT - we add it client-side)
        nordpool_sensor = "sensor.nord_pool_fi_current_price"
        entities.append(nordpool_sensor)
        
        if SETPOINT_OUTPUT and SETPOINT_OUTPUT not in entities:
            entities.append(SETPOINT_OUTPUT)
        if BASE_TEMPERATURE_INPUT and BASE_TEMPERATURE_INPUT not in entities:
            entities.append(BASE_TEMPERATURE_INPUT)
        
        logger.info(f"api_history: Querying {len(entities)} entities for {hours}h")
        
        entity_filter = ','.join(entities)
        end_time_utc = now_utc + timedelta(hours=24)
        end_time = end_time_utc.replace(tzinfo=None).isoformat()
        url = f"{HA_URL}/api/history/period/{start_time_iso}?filter_entity_id={entity_filter}&end_time={end_time}"
        
        response = requests.get(url, headers=HA_HEADERS, timeout=60)
        
        if response.status_code != 200:
            logger.error(f"api_history: HA API error {response.status_code}")
            return jsonify({"error": f"HA API returned {response.status_code}"}), 500
        
        history_data = response.json()
        
        result = {
            "start_time": start_time_iso,
            "end_time": datetime.now().isoformat(),
            "hours": hours,
            "entities": {},
            "temperature_entity": TEMPERATURE_SENSOR,
            "outdoor_temperature_entity": OUTDOOR_TEMP_SENSOR,
            "setpoint_entity": SETPOINT_OUTPUT,
            "base_temperature_entity": BASE_TEMPERATURE_INPUT,
            "room_heater_entity": SWITCH_ENTITY,
            "central_heating_entity": CENTRAL_HEATING_SHUTOFF_SWITCH,
            "nordpool_price_entity": nordpool_sensor
        }
        
        for entity_history in history_data:
            if not entity_history:
                continue
            
            entity_id = entity_history[0].get('entity_id')
            points = []
            
            for state in entity_history:
                try:
                    timestamp = state.get('last_changed')
                    value = state.get('state')
                    
                    if value not in ['on', 'off', 'unavailable', 'unknown']:
                        try:
                            value = float(value)
                            # Apply VAT to Nordpool price sensor (prices come without VAT from HA)
                            if entity_id == nordpool_sensor:
                                value = value * ELECTRICITY_VAT_MULTIPLIER
                        except (ValueError, TypeError):
                            pass
                    
                    points.append({'timestamp': timestamp, 'value': value})
                except Exception:
                    continue
            
            result['entities'][entity_id] = points
        
        return jsonify(result)
    
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route('/api/heating-decisions')
@cache.cached(timeout=900, query_string=True)
def api_heating_decisions():
    """Get heating decisions log (cached for 5 minutes)."""
    try:
        date_str = request.args.get('date')
        limit = request.args.get('limit', type=int)
        
        if date_str:
            decisions = get_decisions_by_date(date_str)
        else:
            decisions = get_decisions(limit=limit)
        
        return jsonify({
            "decisions": decisions,
            "count": len(decisions)
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    """Clear the API cache."""
    try:
        cache.clear()
        return jsonify({"status": "success", "message": "Cache cleared"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Application Startup
# =============================================================================

# Start background tasks when module is imported
start_cache_warmer_once()


if __name__ == '__main__':
    import os
    port = int(os.getenv('WEB_PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
