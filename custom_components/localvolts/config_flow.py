import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, CONF_API_KEY, CONF_PARTNER_ID, CONF_NMI_ID
from . import validate_api_key, validate_partner_id, validate_nmi_id

_LOGGER = logging.getLogger(__name__)

# Define the schema with placeholders for default values
def build_data_schema(existing_data):
    return vol.Schema(
        {
            vol.Required(CONF_API_KEY, default=existing_data.get(CONF_API_KEY, "")): cv.string,
            vol.Required(CONF_PARTNER_ID, default=existing_data.get(CONF_PARTNER_ID, "")): cv.string,
            vol.Required(CONF_NMI_ID, default=existing_data.get(CONF_NMI_ID, "")): cv.string,
        }
    )

class LocalvoltsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Localvolts integration."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        # If this is a reconfiguration, pre-populate with existing data
        existing_entry = next(iter(self._async_current_entries()), None)
        existing_data = existing_entry.data if existing_entry else {}

        #_LOGGER.debug("Existing data: %s", existing_data)

        if user_input is not None:
            # Validate the inputs
            if not validate_api_key(user_input[CONF_API_KEY]):
                errors[CONF_API_KEY] = "invalid_api_key"
            elif not validate_partner_id(user_input[CONF_PARTNER_ID]):
                errors[CONF_PARTNER_ID] = "invalid_partner_id"
            elif not validate_nmi_id(user_input[CONF_NMI_ID]):
                errors[CONF_NMI_ID] = "invalid_nmi_id"

            if not errors:
                # Use the NMI_ID as the title of the integration
                title = f"NMI: {user_input[CONF_NMI_ID]}"
                # Save the configuration and create the entry
                return self.async_create_entry(title=title, data=user_input)
                
        # Show the form if there are errors or if the user input is None
        return self.async_show_form(
            step_id="user", data_schema=build_data_schema(existing_data), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LocalvoltsOptionsFlowHandler(config_entry)

class LocalvoltsOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for the Localvolts integration."""

    def __init__(self, config_entry):
        """Initialize Localvolts options flow."""
        super().__init__(config_entry)

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Manage the options."""
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the options step."""
        errors = {}

        if user_input is not None:
            # Save the updated options
            return self.async_create_entry(title="", data=user_input)

        # Pre-populate with existing options
        options = self.config_entry.options
        return self.async_show_form(
            step_id="user", data_schema=build_data_schema(options), errors=errors
        )
