"""The localvolts integration."""

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.template import Template, render_complex
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from datetime import time, timedelta
import logging
import voluptuous as vol
import aiohttp

from .coordinator import LocalvoltsDataUpdateCoordinator

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_PARTNER_ID,
    CONF_NMI_ID,
    EMHASS_ENABLED,
    EMHASS_ADDRESS
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_API_KEY): cv.string,
                vol.Required(CONF_PARTNER_ID): cv.string,
                vol.Required(CONF_NMI_ID): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry):
    """Set up the Localvolts integration from a config entry."""
    _LOGGER.debug("Setting up the Localvolts component from config entry.")
    
    async def handle_dayahead(call: ServiceCall):
        emhass_address = hass.data[DOMAIN].get("emhass_address")
        if not emhass_address:
            _LOGGER.error("EMHASS address not set in hass.data[DOMAIN][\"emhass_address\"]")
            return
        url = f"{emhass_address}/action/dayahead-optim"
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={})

    async def handle_publish_data(call: ServiceCall):
        emhass_address = hass.data[DOMAIN].get("emhass_address")
        if not emhass_address:
            _LOGGER.error("EMHASS address not set in hass.data[DOMAIN][\"emhass_address\"]")
            return
        url = f"{emhass_address}/action/publish-data"
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={})

    async def handle_naive_mpc_optim(call: ServiceCall):
        # Template context
        emhass_address = hass.data[DOMAIN].get("emhass_address")
        if not emhass_address:
            _LOGGER.error("EMHASS address not set in hass.data[DOMAIN][\"emhass_address\"]")
            return
        url = f"{emhass_address}/action/naive-mpc-optim"

        context = {"states": hass.states, "state_attr": lambda s, a: hass.states.get(s).attributes.get(a) if hass.states.get(s) else None}
        
        # 1. Compute prediction_horizon (equivalent to Jinja2 template)
        forecast = context["state_attr"]('sensor.forecasted_costs_flex_up', 'forecast') or []
        prod_price_forecast = [ (v.get('earningsFlexUp', 0.0) or 0.0) / 100 for v in forecast ]
        load_cost_forecast = [ (v.get('costsFlexUp', 0.0) or 0.0) / 100 for v in forecast ]
        prediction_horizon = min(288, len(prod_price_forecast))
        soc_init = (float(hass.states.get('sensor.sigen_plant_battery_state_of_charge').state or 0)/100) if hass.states.get('sensor.sigen_plant_battery_state_of_charge') else 0

        payload = {
            "prediction_horizon": prediction_horizon,
            "prod_price_forecast": prod_price_forecast,
            "load_cost_forecast": load_cost_forecast,
            "alpha": 0,
            "beta": 1,
            "continual_publish": False,
            "optimization_time_step": 5,
            "soc_init": soc_init
        }
        async with aiohttp.ClientSession() as session:
            await session.post(url, json=payload, timeout=120)

    api_key = config_entry.data[CONF_API_KEY]
    partner_id = config_entry.data[CONF_PARTNER_ID]
    nmi_id = config_entry.data[CONF_NMI_ID]
    emhass_enabled = config_entry.data[EMHASS_ENABLED]
    emhass_address = config_entry.data[EMHASS_ADDRESS]
    # Read EMHASS settings (prefer options, fallback to data) ---
    # emhass_enabled = config_entry.options.get("emhass_enabled", config_entry.data.get("emhass_enabled", False))
    # emhass_address = config_entry.options.get("emhass_address", config_entry.data.get("emhass_address", ""))
    
    # Store them for global access within your integration
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["api_key"] = api_key
    hass.data[DOMAIN]["partner_id"] = partner_id
    hass.data[DOMAIN]["nmi_id"] = nmi_id
    hass.data[DOMAIN]["emhass_enabled"] = emhass_enabled
    hass.data[DOMAIN]["emhass_address"] = emhass_address
    
    # Debug schedule
    _LOGGER.warning("emhass_enabled: %s", hass.data[DOMAIN]["emhass_enabled"])

    # Initialize coordinator
    coordinator = LocalvoltsDataUpdateCoordinator(hass)

    try:
        await coordinator.async_refresh()
        if not coordinator.last_update_success:
            _LOGGER.error("Initial data fetch failed")
            return False
    except Exception as err:
        _LOGGER.error("Error initializing coordinator: %s", err)
        return False

    # Store data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]['coordinator'] = coordinator

    # Load the sensor platform
    await hass.config_entries.async_forward_entry_setups(config_entry, ["sensor"])
    hass.services.async_register("localvolts", "dayahead", handle_dayahead)
    hass.services.async_register("localvolts", "publish_data", handle_publish_data)
    hass.services.async_register("localvolts", "naive_mpc_optim", handle_naive_mpc_optim)
    
   # Function to check emhass_enabled and run day-ahead optimization
    async def maybe_run_dayahead(now):
        if hass.data[DOMAIN].get("emhass_enabled", False):
            await hass.services.async_call("localvolts", "dayahead")

    # Function to check emhass_enabled and run MPC and publish_data
    async def maybe_run_mpc(now):
        _LOGGER.warning("periodic_check called at %s", now)
        if hass.data[DOMAIN].get("emhass_enabled", False):
            await hass.services.async_call("localvolts", "naive_mpc_optim")
            await hass.services.async_call("localvolts", "publish_data")

    # # Register a time trigger for 05:30:00 every day
    # async_track_time_change(
    #     hass,
    #     maybe_run_dayahead,
    #     hour=5,
    #     minute=30,
    #     second=0,
    # )

    # # Register an interval trigger for every 5 minutes at :30s
    # async def periodic_check(now):
    #     # Only at xx:xx:30
    #     if now.second == 30:
    #         await maybe_run_mpc(now)
            
    # async_track_time_interval(
    #     hass,
    #     periodic_check,
    #     timedelta(minutes=5),
    # )
    
    def is_mod_5(n):
        return n % 5 == 0

    async def periodic_check(now):
        # This is running every minute at second 30, but we only want every 5 minutes
        if is_mod_5(now.minute):
            await maybe_run_mpc(now)

    # Register a time trigger for every 5 minutes at :30s
    async_track_time_change(
        hass,
        periodic_check,
        second=30
    )

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, ["sensor"])
    if unload_ok and DOMAIN in hass.data:
        hass.data[DOMAIN].pop("coordinator", None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the localvolts component."""
    _LOGGER.debug("Setting up the localvolts component.")
    # No action needed for YAML configuration, as we are using config entries now
    return True

def validate_api_key(api_key):
    """Validate the API key."""
    expected_length = 32  # Length of a valid API key

    # Check if the API key is of the expected length and a valid hexadecimal
    if len(api_key) == expected_length and all(c in '0123456789abcdef' for c in api_key.lower()):
        return True
    else:
        _LOGGER.error("Invalid API key format or length.")
        return False

def validate_partner_id(partner_id):
    """Validate the Partner ID."""
    # Check if the partner_id is a digit string
    if partner_id.isdigit():
        return True
    else:
        _LOGGER.error("Invalid Partner ID. It should be numeric.")
        return False

def validate_nmi_id(nmi_id):
    """Validate the NMI."""
    expected_length = 11  # Length of a valid NMI is 10 or 11 alphanumeric characters

    # Check if the NMI id is of the expected length and contains only alphanumeric characters
    if 10 <= len(nmi_id) <= expected_length and nmi_id.isalnum():
        return True
    else:
        _LOGGER.error("Invalid NMI id format or length. NMI must be 10-11 alphanumeric characters.")
        return False


