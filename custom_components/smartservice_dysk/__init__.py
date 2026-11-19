# © Smart Service Tczew. Wszelkie prawa zastrzeżone.
"""Smart Service Dysk: the OAuth implementation „Smart Service” for Home Assistant's own Google Drive integration.

Home Assistant's `google_drive` makes the backups; this integration only signs in and refreshes the token through
the Smart Service panel (the Google client's secret stays on the panel, the tokens stay in this home). One entry,
made by Smart Service HA with the panel's Dysk key; no screens of its own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp
from multidict import CIMultiDict, CIMultiDictProxy
import voluptuous as vol
from yarl import URL

from homeassistant.components import websocket_api
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    OAuth2TokenRequestConnectionError,
    OAuth2TokenRequestReauthError,
)
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_KEY, DATA_STATE, DOMAIN, IMPLEMENTATION_NAME, RESULT_WAIT_S, REVOKE_URL, SERVICE_DOMAIN
from .panel import (
    P4,
    PANEL,
    AccountDisabled,
    GrantRevoked,
    KeyInvalid,
    PanelDysk,
    PanelError,
    PanelUnavailable,
    SessionExpired,
)

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _state(hass: HomeAssistant) -> dict[str, Any]:
    """What Smart Service HA reads: the key not known any more, the account switched off."""

    return hass.data.setdefault(DATA_STATE, {"klucz_niewazny": False, "konto_wylaczone": False})


def _entry(hass: HomeAssistant) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries and entries[0].data.get(CONF_KEY) else None


class SmartServiceDyskImplementation(config_entry_oauth2_flow.AbstractOAuth2Implementation):
    """Sign-in and refresh through the panel (the pattern of Home Assistant Cloud's account link)."""

    def __init__(self, hass: HomeAssistant, key: str, *, base: str = PANEL) -> None:
        self.hass = hass
        self._key = key
        self._base = base

    @property
    def name(self) -> str:
        return IMPLEMENTATION_NAME

    @property
    def domain(self) -> str:
        return DOMAIN

    @property
    def service_domain(self) -> str:
        return SERVICE_DOMAIN

    def _panel(self) -> PanelDysk:
        return PanelDysk(async_get_clientsession(self.hass), self._key, base=self._base)

    def _mark(self, err: PanelError) -> None:
        state = _state(self.hass)
        if isinstance(err, KeyInvalid):
            state["klucz_niewazny"] = True
        if isinstance(err, AccountDisabled):
            state["konto_wylaczone"] = True

    async def async_generate_authorize_url(self, flow_id: str) -> str:
        """A new panel session; its address (the panel sends it on to Google) goes to the owner's browser only."""

        try:
            session = await self._panel().start()
        except PanelError as err:
            self._mark(err)
            raise config_entry_oauth2_flow.ImplementationUnavailableError(str(err)) from err

        async def await_tokens() -> None:
            deadline = time.monotonic() + min(session.valid_s, RESULT_WAIT_S)
            panel = self._panel()
            while time.monotonic() < deadline:
                try:
                    result = await panel.result(session.collect)
                except PanelUnavailable as err:
                    await asyncio.sleep(err.retry_after or 2)
                    continue
                except (SessionExpired, PanelError) as err:
                    self._mark(err)
                    _LOGGER.info("Dysk Google: połączenie nie zostało dokończone (%s)", err)
                    return
                if result.state == "czeka":
                    continue
                if result.state == "gotowe" and result.tokens:
                    await self.hass.config_entries.flow.async_configure(flow_id=flow_id, user_input=result.tokens)
                    return
                # The owner said no on Google's page, or the panel could not finish: the flow ends as rejected.
                await self.hass.config_entries.flow.async_configure(flow_id=flow_id, user_input={"error": result.state})
                return
            _LOGGER.info("Dysk Google: czas na zgodę minął")

        self.hass.async_create_background_task(await_tokens(), name="smartservice_dysk: czekam na zgodę Google")
        return session.address

    async def async_resolve_external_data(self, external_data: Any) -> dict:
        """The tokens are already in hand (given once by the panel)."""

        return dict(external_data)

    async def _async_refresh_token(self, token: dict) -> dict:
        try:
            fresh = await self._panel().refresh(str(token.get("refresh_token") or ""))
        except GrantRevoked as err:
            url = URL(f"{self._base}{P4}")
            info = aiohttp.RequestInfo(url, "POST", CIMultiDictProxy(CIMultiDict()), url)
            raise OAuth2TokenRequestReauthError(request_info=info, status=400, domain=SERVICE_DOMAIN) from err
        except PanelError as err:
            # The panel down, the key not known or the account off: no screen, Home Assistant tries again later.
            self._mark(err)
            raise OAuth2TokenRequestConnectionError(domain=SERVICE_DOMAIN) from err
        _state(self.hass).update({"klucz_niewazny": False, "konto_wylaczone": False})
        return {**token, **fresh}


async def _provide(hass: HomeAssistant, domain: str) -> list[config_entry_oauth2_flow.AbstractOAuth2Implementation]:
    """For Google Drive only, and only with the entry Smart Service HA made."""

    if domain != SERVICE_DOMAIN:
        return []
    entry = _entry(hass)
    if entry is None:
        return []
    if _state(hass)["klucz_niewazny"]:
        # Not "gone": the backups wait (no screen) until Smart Service HA gives a new key.
        raise config_entry_oauth2_flow.ImplementationUnavailableError("klucz Dysku czeka na odnowienie")
    return [SmartServiceDyskImplementation(hass, entry.data[CONF_KEY])]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    config_entry_oauth2_flow.async_add_implementation_provider(hass, DOMAIN, _provide)
    websocket_api.async_register_command(hass, ws_state)
    websocket_api.async_register_command(hass, ws_revoke)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _state(hass)["klucz_niewazny"] = False
    _reattach(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True


@callback
def _reattach(hass: HomeAssistant) -> None:
    """Start order (R1): a Google Drive entry of ours that set up before us asked for a new sign-in - that request
    is withdrawn and the entry loaded again, now with our implementation in place. Never another implementation's."""

    for entry in hass.config_entries.async_entries(SERVICE_DOMAIN):
        if entry.data.get("auth_implementation") != DOMAIN:
            continue
        for flow in hass.config_entries.flow.async_progress_by_handler(SERVICE_DOMAIN):
            if flow["context"].get("source") == SOURCE_REAUTH and flow["context"].get("entry_id") == entry.entry_id:
                hass.config_entries.flow.async_abort(flow["flow_id"])
        if entry.state in (ConfigEntryState.SETUP_ERROR, ConfigEntryState.SETUP_RETRY):
            hass.config_entries.async_schedule_reload(entry.entry_id)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartservice_dysk/stan"})
@callback
def ws_state(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """For Smart Service HA: whether the key needs renewing or the account is off (never a key or a token)."""

    connection.send_result(msg["id"], {"wpis": _entry(hass) is not None, **_state(hass)})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartservice_dysk/uniewaznij", vol.Required("entry_id"): str})
@websocket_api.async_response
async def ws_revoke(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """„Odłącz Dysk Google”: the token revoked at Google, only for a Google Drive entry signed in through us.
    Smart Service HA removes the backups' place before and the entry after; the backups on Drive stay."""

    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != SERVICE_DOMAIN or entry.data.get("auth_implementation") != DOMAIN:
        connection.send_error(msg["id"], "not_ours", "To nie jest połączenie Dysku Google przez Smart Service.")
        return
    token = entry.data.get("token") or {}
    value = token.get("refresh_token") or token.get("access_token")
    if not isinstance(value, str) or not value:
        connection.send_result(msg["id"], {"uniewazniono": False})
        return
    try:
        async with async_get_clientsession(hass).post(
            REVOKE_URL, data={"token": value}, timeout=aiohttp.ClientTimeout(total=15)
        ) as response:
            done = response.status in (200, 400)  # 400: Google no longer knows the token - already revoked.
    except (TimeoutError, aiohttp.ClientError):
        done = False
    connection.send_result(msg["id"], {"uniewazniono": done})
