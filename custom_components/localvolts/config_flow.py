"""Config and options flows for the Localvolts integration."""

import logging
import voluptuous as vol

import aiohttp

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, CONF_API_KEY, CONF_PARTNER_ID, CONF_NMI_ID
from .coordinator import LocalvoltsAuthError, async_discover_nmis

_LOGGER = logging.getLogger(__name__)

API_KEY_LENGTH = 32


def _validate_api_key(api_key: str) -> bool:
    """Check the API key looks like the 32-character hex string Localvolts issues."""
    return len(api_key) == API_KEY_LENGTH and all(
        c in "0123456789abcdef" for c in api_key.lower()
    )


def _validate_partner_id(partner_id: str) -> bool:
    """Check the partner ID is numeric, as issued by Localvolts."""
    return partner_id.isdigit()


def _map_auth_error(err: LocalvoltsAuthError) -> dict:
    """Mirrors the API's own documented error text (see coordinator.py) to
    tell an invalid key apart from an unregistered partner."""
    message = str(err).lower()
    if "api key" in message:
        return {CONF_API_KEY: "invalid_api_key"}
    if "partner" in message:
        return {CONF_PARTNER_ID: "invalid_partner_id"}
    return {"base": "cannot_connect"}


async def _async_discover_nmis_or_errors(hass: HomeAssistant, api_key: str, partner_id: str):
    """Format-check api_key/partner_id, then discover the account's NMI(s).

    Shared by the initial config flow and the options (reconfigure) flow,
    since both now collect just these two fields and look up the NMI the
    same way. Returns (nmis, errors) - nmis is None if errors is non-empty.
    """
    errors: dict = {}
    if not api_key:
        errors[CONF_API_KEY] = "required"
    elif not _validate_api_key(api_key):
        errors[CONF_API_KEY] = "invalid_api_key"
    if not partner_id:
        errors[CONF_PARTNER_ID] = "required"
    elif not _validate_partner_id(partner_id):
        errors[CONF_PARTNER_ID] = "invalid_partner_id"

    if errors:
        return None, errors

    try:
        nmis = await async_discover_nmis(hass, api_key, partner_id)
    except LocalvoltsAuthError as err:
        return None, _map_auth_error(err)
    except ValueError:
        return None, {"base": "no_nmi_found"}
    except (TimeoutError, aiohttp.ClientError):
        # TimeoutError is what a ClientTimeout total actually raises - it is
        # not an aiohttp.ClientError, so it needs naming separately or the
        # form would fall through to "unknown error".
        return None, {"base": "cannot_connect"}

    return nmis, {}


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
        with NMI=* returns every NMI this partner/key can see, which also
        doubles as validating the credentials. One NMI found skips straight
        to creating the entry; more than one goes to a picker, instead of
        asking for a hand-typed, easy-to-mistype 11-character code.
        """
        errors = {}
        if user_input is not None:
            api_key = user_input.get(CONF_API_KEY)
            partner_id = user_input.get(CONF_PARTNER_ID)
            nmis, errors = await _async_discover_nmis_or_errors(self.hass, api_key, partner_id)

            if not errors:
                self._api_key = api_key
                self._partner_id = partner_id
                if len(nmis) == 1:
                    return await self._async_create_entry_for_nmi(nmis[0])
                self._nmi_choices = nmis
                return await self.async_step_pick_nmi()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY, default=(user_input or {}).get(CONF_API_KEY, "")): str,
                vol.Required(CONF_PARTNER_ID, default=(user_input or {}).get(CONF_PARTNER_ID, "")): str,
            }),
            errors=errors,
        )

    async def async_step_pick_nmi(self, user_input=None):
        """Let the user pick which discovered NMI to set up, when there's more than one."""
        if user_input is not None:
            return await self._async_create_entry_for_nmi(user_input[CONF_NMI_ID])

        return self.async_show_form(
            step_id="pick_nmi",
            data_schema=vol.Schema({
                vol.Required(CONF_NMI_ID): vol.In(self._nmi_choices),
            }),
        )

    async def _async_create_entry_for_nmi(self, nmi_id: str):
        await self.async_set_unique_id(nmi_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            # Includes the NMI so multiple entries (one per site) are
            # distinguishable in the integrations list, not all just
            # "LocalVolts".
            title=f"LocalVolts ({nmi_id})",
            data={
                CONF_API_KEY: self._api_key,
                CONF_PARTNER_ID: self._partner_id,
                CONF_NMI_ID: nmi_id,
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

    def __init__(self) -> None:
        super().__init__()
        self._api_key: str | None = None
        self._partner_id: str | None = None
        self._nmi_choices: list[str] = []

    async def async_step_init(self, user_input=None):
        """Collect the API key and partner ID, then discover the account's NMI(s) - same as initial setup."""
        errors = {}
        cur = self.config_entry.data
        if user_input is not None:
            api_key = user_input.get(CONF_API_KEY)
            partner_id = user_input.get(CONF_PARTNER_ID)
            nmis, errors = await _async_discover_nmis_or_errors(self.hass, api_key, partner_id)

            if not errors:
                self._api_key = api_key
                self._partner_id = partner_id
                self._nmi_choices = nmis
                return await self.async_step_pick_nmi()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY, default=(user_input or {}).get(CONF_API_KEY, cur.get(CONF_API_KEY, ""))): str,
                vol.Required(CONF_PARTNER_ID, default=(user_input or {}).get(CONF_PARTNER_ID, cur.get(CONF_PARTNER_ID, ""))): str,
            }),
            errors=errors,
        )

    async def async_step_pick_nmi(self, user_input=None):
        """Confirm or change which discovered NMI this entry manages."""
        errors = {}
        current_nmi = self.config_entry.data.get(CONF_NMI_ID)

        if user_input is not None:
            new_nmi_id = user_input[CONF_NMI_ID]
            nmi_changed = new_nmi_id != current_nmi

            # Changing the NMI here would otherwise leave this entry's own
            # unique_id pointing at the old NMI - silently breaking the
            # duplicate-NMI check both ways: the old NMI would look falsely
            # "already configured" if re-added, and the new NMI wouldn't
            # look configured at all even though it now is.
            if nmi_changed and any(
                entry.unique_id == new_nmi_id
                for entry in self.hass.config_entries.async_entries(DOMAIN)
                if entry.entry_id != self.config_entry.entry_id
            ):
                errors[CONF_NMI_ID] = "already_configured"
            else:
                # Credentials live in config_entry.data (that's what
                # async_setup_entry reads) - OptionsFlow.async_create_entry
                # only writes config_entry.options, which is never read, so
                # update .data directly and reload for the change to
                # actually take effect.
                update_kwargs = {
                    "data": {
                        CONF_API_KEY: self._api_key,
                        CONF_PARTNER_ID: self._partner_id,
                        CONF_NMI_ID: new_nmi_id,
                    }
                }
                if nmi_changed:
                    update_kwargs["unique_id"] = new_nmi_id
                self.hass.config_entries.async_update_entry(
                    self.config_entry, **update_kwargs
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})

        # Pre-select the entry's current NMI if it's still in the
        # discovered list; otherwise (e.g. different credentials that don't
        # cover it) leave it unselected rather than defaulting to one that
        # may not even be right.
        if current_nmi in self._nmi_choices:
            nmi_key = vol.Required(CONF_NMI_ID, default=current_nmi)
        else:
            nmi_key = vol.Required(CONF_NMI_ID)

        return self.async_show_form(
            step_id="pick_nmi",
            data_schema=vol.Schema({nmi_key: vol.In(self._nmi_choices)}),
            errors=errors,
        )
