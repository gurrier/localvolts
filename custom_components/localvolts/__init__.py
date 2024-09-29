"""The localvolts integration."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
import logging
import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .coordinator import LocalvoltsDataUpdateCoordinator

DOMAIN = "localvolts"

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required('api_key'): cv.string,
        vol.Required('partner_id'): cv.string,
        vol.Required('nmi_id'): cv.string,
    }),
}, extra=vol.ALLOW_EXTRA)

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the localvolts component."""
    _LOGGER.debug("Setting up the localvolts component.")

    conf = config[DOMAIN]
    api_key = conf['api_key']
    partner_id = conf['partner_id']
    nmi_id = conf['nmi_id']

    # Validation
    if not validate_api_key(api_key):
        _LOGGER.error("Invalid API key provided.")
        return False

    if not validate_partner_id(partner_id):
        _LOGGER.error("Invalid Partner ID provided.")
        return False

    if not validate_nmi_id(nmi_id):
        _LOGGER.error("Invalid NMI ID provided.")
        return False

    # Initialize coordinator
    coordinator = LocalvoltsDataUpdateCoordinator(
        hass, api_key, partner_id, nmi_id
    )

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
    hass.async_create_task(
        discovery.async_load_platform(hass, 'sensor', DOMAIN, {}, config)
    )

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
    expected_length = 11  # Length of a valid NMI is 10 or 11 numerical digits

    # Check if the NMI id is of the expected length and a valid number
    if len(nmi_id) <= expected_length and all(c in '0123456789' for c in nmi_id):
        return True
    else:
        _LOGGER.error("Invalid NMI id format or length.")
        return False
