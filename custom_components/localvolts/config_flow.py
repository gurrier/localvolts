import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN
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
            elif not validate_api_key(api_key):
                errors["api_key"] = "invalid_api_key"
            if not partner_id:
                errors["partner_id"] = "required"
            elif not validate_partner_id(partner_id):
                errors["partner_id"] = "invalid_partner_id"
            if not nmi_id:
                errors["nmi_id"] = "required"
            elif not validate_nmi_id(nmi_id):
                errors["nmi_id"] = "invalid_nmi_id"

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
        return LocalvoltsOptionsFlowHandler()

class LocalvoltsOptionsFlowHandler(config_entries.OptionsFlow):
    # No __init__/self.config_entry assignment here - manually setting it is
    # deprecated (HA issue: "stops working in 2025.12"). OptionsFlow already
    # provides self.config_entry as a property.

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            api_key = user_input.get("api_key")
            partner_id = user_input.get("partner_id")
            nmi_id = user_input.get("nmi_id")

            if not api_key:
                errors["api_key"] = "required"
            elif not validate_api_key(api_key):
                errors["api_key"] = "invalid_api_key"
            if not partner_id:
                errors["partner_id"] = "required"
            elif not validate_partner_id(partner_id):
                errors["partner_id"] = "invalid_partner_id"
            if not nmi_id:
                errors["nmi_id"] = "required"
            elif not validate_nmi_id(nmi_id):
                errors["nmi_id"] = "invalid_nmi_id"

            if not errors:
                # Credentials live in config_entry.data (that's what
                # async_setup_entry reads) - OptionsFlow.async_create_entry
                # only writes config_entry.options, which is never read, so
                # update .data directly and reload for the change to
                # actually take effect.
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=user_input
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})

        # Defaults reflect what's actually in use (config_entry.data)
        cur = self.config_entry.data

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("api_key", default=(user_input or {}).get("api_key", cur.get("api_key", ""))): str,
                vol.Required("partner_id", default=(user_input or {}).get("partner_id", cur.get("partner_id", ""))): str,
                vol.Required("nmi_id", default=(user_input or {}).get("nmi_id", cur.get("nmi_id", ""))): str,
            }),
            errors=errors,
        )
