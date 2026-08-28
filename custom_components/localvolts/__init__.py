"""The localvolts integration."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
import logging
import voluptuous as vol

from .coordinator import LocalvoltsDataUpdateCoordinator

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_PARTNER_ID,
    CONF_NMI_ID
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


async def _async_migrate_unique_ids(hass: HomeAssistant, config_entry, nmi_id: str) -> None:
    """Rename unique_ids left over from the 0.6.0/0.6.1 'localvolts_' prefix experiment.

    0.6.0/0.6.1 briefly renamed every sensor's unique_id to add a "localvolts_"
    prefix, then 0.6.2 reverted it, in both cases without a working migration
    (the "_attr_old_unique_ids" attribute used at the time isn't a real HA
    mechanism). This renames any entities still on a legacy id in place so
    existing entity_ids and history are preserved instead of duplicating.
    """
    legacy_to_current = {
        f"localvolts_{nmi_id}_costsFlexUp": f"{nmi_id}_costsFlexUp",
        f"localvolts_{nmi_id}_earningsFlexUp": f"{nmi_id}_earningsFlexUp",
        f"localvolts_{nmi_id}_datalag": f"{nmi_id}_data_lag",
        f"{nmi_id}_datalag": f"{nmi_id}_data_lag",
        f"localvolts_{nmi_id}_intervalend": f"{nmi_id}_interval_end",
        f"{nmi_id}_intervalend": f"{nmi_id}_interval_end",
        f"localvolts_{nmi_id}_forecast_costs_flex_up": f"{nmi_id}_forecast_costs_flex_up",
    }

    registry = er.async_get(hass)
    for entry in er.async_entries_for_config_entry(registry, config_entry.entry_id):
        new_unique_id = legacy_to_current.get(entry.unique_id)
        if new_unique_id and new_unique_id != entry.unique_id:
            _LOGGER.info(
                "Migrating Localvolts entity %s unique_id %s -> %s",
                entry.entity_id, entry.unique_id, new_unique_id,
            )
            registry.async_update_entity(entry.entity_id, new_unique_id=new_unique_id)


async def async_setup_entry(hass, config_entry):
    """Set up the Localvolts integration from a config entry."""
    _LOGGER.debug("Setting up the Localvolts component from config entry.")
    
    api_key = config_entry.data[CONF_API_KEY]
    partner_id = config_entry.data[CONF_PARTNER_ID]
    nmi_id = config_entry.data[CONF_NMI_ID]

    await _async_migrate_unique_ids(hass, config_entry, nmi_id)

    # Entries created before the config entry itself carried a unique_id
    # (tied to the NMI) have none set, so the duplicate-NMI check in
    # config_flow.py can't see them as already configured. Backfill it here
    # so that protection actually covers entries that predate it.
    if config_entry.unique_id != nmi_id:
        hass.config_entries.async_update_entry(config_entry, unique_id=nmi_id)

    # Entries created before entry titles included the NMI are stuck on the
    # generic "LocalVolts" - upgrade those, but only that exact default, so
    # a title someone's already customised themselves is left alone.
    if config_entry.title == "LocalVolts":
        hass.config_entries.async_update_entry(config_entry, title=f"LocalVolts ({nmi_id})")

    # Read the version from the manifest rather than hardcoding it anywhere
    # else, so the User-Agent sent to the Localvolts API always matches
    # whatever's actually installed with no separate value to keep in sync.
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version) if integration.version else "unknown"

    # Initialize coordinator
    coordinator = LocalvoltsDataUpdateCoordinator(hass, api_key, partner_id, nmi_id, version)

    try:
        await coordinator.async_refresh()
        if not coordinator.last_update_success:
            _LOGGER.error("Initial data fetch failed")
            return False
    except Exception as err:
        _LOGGER.error("Error initializing coordinator: %s", err)
        return False

    # Store on the entry itself rather than a hass.data[DOMAIN] dict keyed by
    # entry_id - besides being the current convention, it rules out the kind
    # of key-collision-between-entries bug fixed in gurrier/localvolts#22.
    config_entry.runtime_data = coordinator

    # Load the sensor platform
    await hass.config_entries.async_forward_entry_setups(config_entry, ["sensor"])

    return True

async def async_unload_entry(hass: HomeAssistant, config_entry):
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(config_entry, ["sensor"])


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



