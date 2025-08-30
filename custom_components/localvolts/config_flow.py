import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, CONF_API_KEY, CONF_PARTNER_ID, CONF_NMI_ID, EMHASS_ENABLED, EMHASS_ADDRESS
from . import validate_api_key, validate_partner_id, validate_nmi_id

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(EMHASS_ENABLED, default=False): bool,
        # Don't add address here, only show if toggle is true
        # ... any other fields ...
    }
)

STEP_EMHASS_SCHEMA = vol.Schema(
    {
        vol.Required(EMHASS_ADDRESS): str,
    }
)
# Add these for options flow too
OPTIONS_USER_SCHEMA = vol.Schema(
    {
        vol.Optional(EMHASS_ENABLED, default=False): bool,
    }
)
OPTIONS_EMHASS_SCHEMA = vol.Schema(
    {
        vol.Required(EMHASS_ADDRESS): str,
    }
)

# Define the schema with placeholders for default values
def build_data_schema(existing_data):
    return vol.Schema(
        {
            vol.Required(CONF_API_KEY, default=existing_data.get(CONF_API_KEY, "")): cv.string,
            vol.Required(CONF_PARTNER_ID, default=existing_data.get(CONF_PARTNER_ID, "")): cv.string,
            vol.Required(CONF_NMI_ID, default=existing_data.get(CONF_NMI_ID, "")): cv.string,
        }
    )
    
def validate_emhass_address(address: str) -> bool:
    """Basic validation for EMHASS server address."""
    return address.startswith("http://") or address.startswith("https://")

class LocalVoltsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
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

            if not api_key:
                errors["api_key"] = "required"
            if not partner_id:
                errors["partner_id"] = "required"
            if not nmi_id:
                errors["nmi_id"] = "required"
            if emhass_enabled and not emhass_address:
                errors["emhass_address"] = "required"

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
            }),
            errors=errors,
        )
                
    # async def async_step_emhass(self, user_input=None):
    #     errors = {}
    #     if user_input is not None:
    #         self._options.update(user_input)  # will just contain emhass fields
    #         to_save = self._user_input.copy()
    #         to_save.update(self._options)
    #         title = f"NMI: {to_save.get(CONF_NMI_ID, '')}"
    #         return self.async_create_entry(title=title, data=to_save)
    #     return self.async_show_form(
    #         step_id="emhass",
    #         data_schema=vol.Schema({
    #             vol.Required(
    #                 EMHASS_ADDRESS,
    #                 default=self._options.get(EMHASS_ADDRESS, "")
    #             ): str,
    #         }),
    #         errors=errors
    #     )
        
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LocalvoltsOptionsFlowHandler(config_entry)

class LocalVoltsOptionsFlowHandler(config_entries.OptionsFlow):
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

            if not api_key:
                errors["api_key"] = "required"
            if not partner_id:
                errors["partner_id"] = "required"
            if not nmi_id:
                errors["nmi_id"] = "required"
            if emhass_enabled and not emhass_address:
                errors["emhass_address"] = "required"

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
            }),
            errors=errors,
        )

    # async def async_step_emhass(self, user_input=None):
    #     errors = {}
    #     # Show the address input, prefilled if previously set
    #     if user_input is not None:
    #         self._options.update(user_input)
    #         return self.async_create_entry(title="", data=self._options)
    #     return self.async_show_form(
    #         step_id="emhass",
    #         data_schema=vol.Schema({
    #             vol.Required(
    #                 EMHASS_ADDRESS,
    #                 default=self._options.get(EMHASS_ADDRESS, "")
    #             ): str,
    #         }),
    #         errors=errors
    #     )