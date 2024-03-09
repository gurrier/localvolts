"""The localvolts integration."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
import logging
import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant.exceptions import PlatformNotReady

DOMAIN = "localvolts"

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required('api_key'): cv.string,
        vol.Required('partner_id'): cv.string,
        vol.Required('nmi_id'): cv.string,
        # Include other configuration parameters here if needed
    }),
}, extra=vol.ALLOW_EXTRA)


_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the localvolts_sensor component."""
    _LOGGER.debug("Setting up the localvolts component.")

#    _LOGGER.debug("Config: %s", config)

    conf = config[DOMAIN]
    api_key = conf['api_key']
    partner_id = conf['partner_id']
    nmi_id = conf['nmi_id']

    # Example validation - replace with actual validation logic
    if not validate_api_key(api_key):
        _LOGGER.error("Invalid API key provided.")
        raise PlatformNotReady("Invalid API key.")

    if not validate_partner_id(partner_id):
        _LOGGER.error("Invalid Partner ID provided.")
        raise PlatformNotReady("Invalid Partner ID.")

    if not validate_nmi_id(nmi_id):
        _LOGGER.error("Invalid NMI ID provided.")
        raise PlatformNotReady("Invalid NMI ID.")

    # You can now use apikey and partner is and nmi id for further setup or store them
    hass.data[DOMAIN] = {
        'api_key': api_key,
        'partner_id': partner_id,
        'nmi_id': nmi_id
    }
    
    _LOGGER.debug("api_key = %s", api_key)
    _LOGGER.debug("partner_id = %s", partner_id)
    _LOGGER.debug("nmi_id = %s", nmi_id)
    
    _LOGGER.debug("Load the sensor platform, passing the configuration")
    # Load the sensor platform, passing the configuration
    hass.async_create_task(
        discovery.async_load_platform(hass, 'sensor', DOMAIN, {}, config)
    )
    _LOGGER.debug("hass.async_create_task complete")
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