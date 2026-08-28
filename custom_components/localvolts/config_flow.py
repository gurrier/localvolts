import logging
import voluptuous as vol

import aiohttp

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from . import validate_api_key, validate_partner_id, validate_nmi_id
from .coordinator import LocalvoltsAuthError, async_validate_credentials

_LOGGER = logging.getLogger(__name__)


async def _async_validate_input(hass: HomeAssistant, user_input: dict) -> dict:
    """Check field formats, then make a real API call to confirm they work.

    Shared between the initial config flow and the options (reconfigure)
    flow, since both collect and validate the same three fields the same
    way. Returns a dict of field-name -> error code, empty if everything's
    good.
    """
    errors: dict = {}
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

    if errors:
        return errors

    try:
        await async_validate_credentials(hass, api_key, partner_id, nmi_id)
    except LocalvoltsAuthError as err:
        # Mirrors the API's own documented error text (see coordinator.py)
        # to tell an invalid key apart from an unregistered partner.
        message = str(err).lower()
        if "api key" in message:
            errors["api_key"] = "invalid_api_key"
        elif "partner" in message:
            errors["partner_id"] = "invalid_partner_id"
        else:
            errors["base"] = "cannot_connect"
    except ValueError:
        errors["nmi_id"] = "invalid_nmi_id"
    except aiohttp.ClientError:
        errors["base"] = "cannot_connect"

    return errors


class LocalvoltsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            errors = await _async_validate_input(self.hass, user_input)

            if not errors:
                await self.async_set_unique_id(user_input["nmi_id"])
                self._abort_if_unique_id_configured()
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
            errors = await _async_validate_input(self.hass, user_input)

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
