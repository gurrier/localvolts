import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import selector

from .const import DOMAIN, CONF_API_KEY, CONF_PARTNER_ID, CONF_NMI_ID, EMHASS_ENABLED, EMHASS_ADDRESS, EMHASS_BATTERY_SOC_ENTITY
from . import validate_api_key, validate_partner_id, validate_nmi_id

_LOGGER = logging.getLogger(__name__)
    
def validate_emhass_address(address: str) -> bool:
    """Basic validation for EMHASS server address."""
    return address.startswith("http://") or address.startswith("https://")

class LocalvoltsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Validate required fields
            api_key = user_input.get("api_key")
            partner_id = user_input.get("partner_id")
            nmi_id = user_input.get("nmi_id")
            emhass_enabled = user_input.get("emhass_enabled", False)
            emhass_address = user_input.get("emhass_address")
            emhass_battery_soc_entity = user_input.get("emhass_battery_soc_entity")

            if not api_key:
                errors["api_key"] = "required"
            if not partner_id:
                errors["partner_id"] = "required"
            if not nmi_id:
                errors["nmi_id"] = "required"
            if emhass_enabled and not emhass_address:
                errors["emhass_address"] = "required"
            if emhass_enabled and not emhass_battery_soc_entity:
                errors["emhass_battery_soc_entity"] = "required"

            if not errors:
                return self.async_create_entry(title="LocalVolts", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("api_key", default=(user_input or {}).get("api_key", "")): str,
                vol.Required("partner_id", default=(user_input or {}).get("partner_id", "")): str,
                vol.Required("nmi_id", default=(user_input or {}).get("nmi_id", "")): str,
                vol.Optional("emhass_enabled", default=(user_input or {}).get("emhass_enabled", False)): bool,
                vol.Optional("emhass_address", default=(user_input or {}).get("emhass_address", "")): str,
        #         vol.Optional("emhass_battery_soc_entity", default=(user_input or {}).get("emhass_battery_soc_entity", cur.get("emhass_battery_soc_entity", ""))
        # ): str,
                vol.Optional(
                    "emhass_battery_soc_entity",
                    default=(user_input or {}).get("emhass_battery_soc_entity", ""),
                ): selector({
                    "entity": {"domain": "sensor"}
                }),
            }),
            errors=errors,
        )
        
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LocalvoltsOptionsFlowHandler(config_entry)

class LocalvoltsOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            api_key = user_input.get("api_key")
            partner_id = user_input.get("partner_id")
            nmi_id = user_input.get("nmi_id")
            emhass_enabled = user_input.get("emhass_enabled", False)
            emhass_address = user_input.get("emhass_address")
            emhass_battery_soc_entity = user_input.get("emhass_battery_soc_entity")

            if not api_key:
                errors["api_key"] = "required"
            if not partner_id:
                errors["partner_id"] = "required"
            if not nmi_id:
                errors["nmi_id"] = "required"
            if emhass_enabled and not emhass_address:
                errors["emhass_address"] = "required"
            if emhass_enabled and not emhass_battery_soc_entity:
                errors["emhass_battery_soc_entity"] = "required"

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        # Use current options or entry data as defaults
        cur = {**self.config_entry.data, **self.config_entry.options}

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("api_key", default=(user_input or {}).get("api_key", cur.get("api_key", ""))): str,
                vol.Required("partner_id", default=(user_input or {}).get("partner_id", cur.get("partner_id", ""))): str,
                vol.Required("nmi_id", default=(user_input or {}).get("nmi_id", cur.get("nmi_id", ""))): str,
                vol.Optional("emhass_enabled", default=(user_input or {}).get("emhass_enabled", cur.get("emhass_enabled", False))): bool,
                vol.Optional("emhass_address", default=(user_input or {}).get("emhass_address", cur.get("emhass_address", ""))): str,
                # <<--- this will provide a UI dropdown for entities!
                vol.Optional(
                    "emhass_battery_soc_entity",
                    default=(user_input or {}).get("emhass_battery_soc_entity", cur.get("emhass_battery_soc_entity", "")),
                ): selector({
                    "entity": {
                        "domain": "sensor",  # filter for only sensor.* entities
                        # optionally, you can use "device_class": ... to further restrict
                    }
                }),
            }),
            errors=errors,
        )
