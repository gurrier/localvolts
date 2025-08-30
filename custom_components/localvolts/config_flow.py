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

class LocalvoltsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Localvolts integration."""

    VERSION = 1
    def __init__(self):
        super().__init__()
        self._user_input = {}
        self._options = {}  # <-- needed for storing across steps

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        existing_entry = next(iter(self._async_current_entries()), None)
        existing_data = existing_entry.data if existing_entry else {}

        # Use build_data_schema to show API/Partner/NMI fields AND the EMHASS toggle
        schema = build_data_schema(existing_data).extend({
            vol.Optional(EMHASS_ENABLED, default=existing_data.get(EMHASS_ENABLED, False)): bool,
        })

        if user_input is not None:
            self._user_input = user_input.copy()  # store full config here
            if user_input.get(EMHASS_ENABLED):
                return await self.async_step_emhass()
            if not validate_api_key(user_input[CONF_API_KEY]):
                errors[CONF_API_KEY] = "invalid_api_key"
            elif not validate_partner_id(user_input[CONF_PARTNER_ID]):
                errors[CONF_PARTNER_ID] = "invalid_partner_id"
            elif not validate_nmi_id(user_input[CONF_NMI_ID]):
                errors[CONF_NMI_ID] = "invalid_nmi_id"

            if not errors:
                title = f"NMI: {user_input[CONF_NMI_ID]}"
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
                
    async def async_step_emhass(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._options.update(user_input)  # will just contain emhass fields
            to_save = self._user_input.copy()
            to_save.update(self._options)
            title = f"NMI: {to_save.get(CONF_NMI_ID, '')}"
            return self.async_create_entry(title=title, data=to_save)
        return self.async_show_form(
            step_id="emhass",
            data_schema=vol.Schema({
                vol.Required(
                    EMHASS_ADDRESS,
                    default=self._options.get(EMHASS_ADDRESS, "")
                ): str,
            }),
            errors=errors
        )
        
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LocalvoltsOptionsFlowHandler(config_entry)

class LocalvoltsOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for the Localvolts integration."""

    def __init__(self, config_entry):
        super().__init__()
        self.config_entry = config_entry
        # Start with all current options
        self._options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None):
        errors = {}

        # Always show API key, partner id, NMI, EMHASS enabled (toggle)
        # Don't show address unless toggle is on
        current = self._options if self._options else self.config_entry.data
        
        data_schema = build_data_schema(current)
        data_schema = data_schema.extend({
            vol.Optional(
                EMHASS_ENABLED,
                default=current.get(EMHASS_ENABLED, False)
            ): bool,
        })

        if user_input is not None:
            self._options.update(user_input)
            # If EMHASS is enabled, ask for address next
            if user_input.get(EMHASS_ENABLED):
                return await self.async_step_emhass()
            # Otherwise save all fields
            return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_emhass(self, user_input=None):
        errors = {}
        # Show the address input, prefilled if previously set
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)
        return self.async_show_form(
            step_id="emhass",
            data_schema=vol.Schema({
                vol.Required(
                    EMHASS_ADDRESS,
                    default=self._options.get(EMHASS_ADDRESS, "")
                ): str,
            }),
            errors=errors
        )