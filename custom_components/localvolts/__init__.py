"""The localvolts integration."""

from homeassistant.core import HomeAssistant

import logging
import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from .coordinator import LocalvoltsDataUpdateCoordinator

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_PARTNER_ID,
    CONF_NMI_ID,
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

async def async_setup_entry(hass: HomeAssistant, config_entry):
    """Set up the Localvolts integration from a config entry."""
    _LOGGER.debug("Setting up the Localvolts component from config entry.")

    api_key = config_entry.data[CONF_API_KEY]
    partner_id = config_entry.data[CONF_PARTNER_ID]
    nmi_id = config_entry.data[CONF_NMI_ID]

    # Initialize coordinator
    coordinator = LocalvoltsDataUpdateCoordinator(hass, api_key, partner_id, nmi_id)

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

    return True


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


