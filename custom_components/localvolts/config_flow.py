import logging
import voluptuous as vol

import aiohttp

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from . import validate_api_key, validate_partner_id, validate_nmi_id
from .coordinator import LocalvoltsAuthError, async_discover_nmis, async_validate_credentials

_LOGGER = logging.getLogger(__name__)


def _map_auth_error(err: LocalvoltsAuthError) -> dict:
    """Mirrors the API's own documented error text (see coordinator.py) to
    tell an invalid key apart from an unregistered partner."""
    message = str(err).lower()
    if "api key" in message:
        return {"api_key": "invalid_api_key"}
    if "partner" in message:
        return {"partner_id": "invalid_partner_id"}
    return {"base": "cannot_connect"}


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
        errors.update(_map_auth_error(err))
    except ValueError:
        errors["nmi_id"] = "invalid_nmi_id"
    except aiohttp.ClientError:
        errors["base"] = "cannot_connect"

    return errors


class LocalvoltsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._api_key: str | None = None
        self._partner_id: str | None = None
        self._nmi_choices: list[str] = []

    async def async_step_user(self, user_input=None):
        """Collect the API key and partner ID, then discover the account's NMI(s).

        The NMI itself is no longer typed in here - GET /customer/interval
        with no NMI argument returns every NMI this partner/key can see
        (confirmed against the real API - see the API guide's note that an
        absent NMI defaults to '*'), which also doubles as validating the
        credentials. One NMI found skips straight to creating the entry;
        more than one goes to a picker instead of asking for a hand-typed,
        easy-to-mistype 11-character code.
        """
        errors = {}
        if user_input is not None:
            api_key = user_input.get("api_key")
            partner_id = user_input.get("partner_id")

            if not api_key:
                errors["api_key"] = "required"
            elif not validate_api_key(api_key):
                errors["api_key"] = "invalid_api_key"
            if not partner_id:
                errors["partner_id"] = "required"
            elif not validate_partner_id(partner_id):
                errors["partner_id"] = "invalid_partner_id"

            if not errors:
                try:
                    nmis = await async_discover_nmis(self.hass, api_key, partner_id)
                except LocalvoltsAuthError as err:
                    errors.update(_map_auth_error(err))
                except ValueError:
                    errors["base"] = "no_nmi_found"
                except aiohttp.ClientError:
                    errors["base"] = "cannot_connect"
                else:
                    self._api_key = api_key
                    self._partner_id = partner_id
                    if len(nmis) == 1:
                        return await self._async_create_entry_for_nmi(nmis[0])
                    self._nmi_choices = nmis
                    return await self.async_step_pick_nmi()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("api_key", default=(user_input or {}).get("api_key", "")): str,
                vol.Required("partner_id", default=(user_input or {}).get("partner_id", "")): str,
            }),
            errors=errors,
        )

    async def async_step_pick_nmi(self, user_input=None):
        """Let the user pick which discovered NMI to set up, when there's more than one."""
        if user_input is not None:
            return await self._async_create_entry_for_nmi(user_input["nmi_id"])

        return self.async_show_form(
            step_id="pick_nmi",
            data_schema=vol.Schema({
                vol.Required("nmi_id"): vol.In(self._nmi_choices),
            }),
        )

    async def _async_create_entry_for_nmi(self, nmi_id: str):
        await self.async_set_unique_id(nmi_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="LocalVolts",
            data={
                "api_key": self._api_key,
                "partner_id": self._partner_id,
                "nmi_id": nmi_id,
            },
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
