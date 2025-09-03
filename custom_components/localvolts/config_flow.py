import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import selector

from .const import DOMAIN, CONF_API_KEY, CONF_PARTNER_ID, CONF_NMI_ID
from . import validate_api_key, validate_partner_id, validate_nmi_id

_LOGGER = logging.getLogger(__name__)
    
class LocalvoltsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Validate required fields
            api_key = user_input.get("api_key")
            partner_id = user_input.get("partner_id")
            nmi_id = user_input.get("nmi_id")

            if not api_key:
                errors["api_key"] = "required"
            if not partner_id:
                errors["partner_id"] = "required"
            if not nmi_id:
                errors["nmi_id"] = "required"

            if not errors:
                return self.async_create_entry(title="LocalVolts", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("api_key", default=(user_input or {}).get("api_key", "")): str,
                vol.Required("partner_id", default=(user_input or {}).get("partner_id", "")): str,
                vol.Required("nmi_id", default=(user_input or {}).get("nmi_id", "")): str,
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

            if not api_key:
                errors["api_key"] = "required"
            if not partner_id:
                errors["partner_id"] = "required"
            if not nmi_id:
                errors["nmi_id"] = "required"

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
            }),
            errors=errors,
        )
