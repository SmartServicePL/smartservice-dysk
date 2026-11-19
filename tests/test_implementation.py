# © Smart Service Tczew. Wszelkie prawa zastrzeżone.
"""The OAuth implementation „Smart Service” for google_drive against a local stand-in of the panel.

Home Assistant itself cannot run on this computer (it needs Linux), so `hass` is a small stand-in with only what the
implementation touches; the panel is a real local aiohttp server speaking the /oauth/dysk* contract.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

from aiohttp import ClientSession, web
import pytest

from homeassistant.exceptions import OAuth2TokenRequestConnectionError, OAuth2TokenRequestReauthError
from homeassistant.helpers import config_entry_oauth2_flow

import custom_components.smartservice_dysk as dysk

TOKENS = {"access_token": "dostep-1", "refresh_token": "odswiez-1", "expires_in": 3599, "token_type": "Bearer",
          "scope": "https://www.googleapis.com/auth/drive.file"}


class FakeHass:
    def __init__(self, entries: list[Any]) -> None:
        self.data: dict[str, Any] = {}
        self.configured: list[tuple[str, dict]] = []
        self.tasks: list[asyncio.Task] = []
        hass = self

        class Flow:
            async def async_configure(self, *, flow_id: str, user_input: dict) -> None:
                hass.configured.append((flow_id, user_input))

        self.config_entries = SimpleNamespace(async_entries=lambda domain: entries if domain == dysk.DOMAIN else [],
                                              flow=Flow())

    def async_create_background_task(self, coro: Awaitable[Any], name: str) -> None:
        self.tasks.append(asyncio.ensure_future(coro))


def with_panel(routes: dict[str, Callable[[web.Request], Awaitable[web.Response]]],
               test: Callable[[str, ClientSession], Awaitable[Any]], monkeypatch: pytest.MonkeyPatch) -> Any:
    async def main() -> Any:
        app = web.Application()
        for path, handler in routes.items():
            app.router.add_post(path, handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        try:
            async with ClientSession() as session:
                monkeypatch.setattr(dysk, "async_get_clientsession", lambda hass: session)
                return await test(f"http://127.0.0.1:{port}", session)
        finally:
            await runner.cleanup()

    return asyncio.run(main())


def test_provider_only_for_google_drive_and_only_with_our_entry() -> None:
    entry = SimpleNamespace(data={"klucz": "k" * 30})
    hass = FakeHass([entry])
    assert asyncio.run(dysk._provide(hass, "spotify")) == []
    found = asyncio.run(dysk._provide(hass, "google_drive"))
    assert [impl.domain for impl in found] == ["smartservice_dysk"] and found[0].service_domain == "google_drive"
    assert found[0].name == "Smart Service"
    assert asyncio.run(dysk._provide(FakeHass([]), "google_drive")) == []
    # A key the panel no longer knows: unavailable (Home Assistant retries, no new sign-in screen).
    dysk._state(hass)["klucz_niewazny"] = True
    with pytest.raises(config_entry_oauth2_flow.ImplementationUnavailableError):
        asyncio.run(dysk._provide(hass, "google_drive"))


def _session(request: web.Request) -> web.Response:
    address = f"http://{request.host}/oauth/dysk/start?s=abc"
    return web.json_response({"adres": address, "odbior": "odb-1", "wazna_s": 600})


def test_sign_in_passes_the_tokens_once_to_the_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([{"stan": "czeka"}, {"stan": "gotowe", "tokeny": TOKENS}])

    async def sesja(request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == "Bearer klucz-dysku"
        return _session(request)

    async def wynik(request: web.Request) -> web.Response:
        assert await request.json() == {"odbior": "odb-1"}
        return web.json_response(next(answers))

    async def test(base: str, _s: ClientSession) -> Any:
        hass = FakeHass([])
        impl = dysk.SmartServiceDyskImplementation(hass, "klucz-dysku", base=base)
        url = await impl.async_generate_authorize_url("flow-1")
        await asyncio.gather(*hass.tasks)
        return url, hass.configured, await impl.async_resolve_external_data(hass.configured[0][1])

    url, configured, resolved = with_panel({"/oauth/dysk/sesja": sesja, "/oauth/dysk/wynik": wynik}, test, monkeypatch)
    assert url.endswith("/oauth/dysk/start?s=abc")
    assert configured == [("flow-1", TOKENS)]
    assert resolved == TOKENS


def test_a_refusal_ends_the_flow_as_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def sesja(request: web.Request) -> web.Response:
        return _session(request)

    async def wynik(_request: web.Request) -> web.Response:
        return web.json_response({"stan": "odmowa"})

    async def test(base: str, _s: ClientSession) -> Any:
        hass = FakeHass([])
        await dysk.SmartServiceDyskImplementation(hass, "k", base=base).async_generate_authorize_url("flow-2")
        await asyncio.gather(*hass.tasks)
        return hass.configured

    assert with_panel({"/oauth/dysk/sesja": sesja, "/oauth/dysk/wynik": wynik}, test, monkeypatch) == [
        ("flow-2", {"error": "odmowa"})
    ]


def test_refresh_through_the_panel_and_its_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    plan: list[tuple[int, dict]] = []

    async def odswiez(request: web.Request) -> web.Response:
        status, body = plan.pop(0)
        return web.json_response(body, status=status)

    async def test(base: str, _s: ClientSession) -> Any:
        hass = FakeHass([])
        impl = dysk.SmartServiceDyskImplementation(hass, "k", base=base)
        fresh = {"access_token": "dostep-2", "expires_in": 3599, "token_type": "Bearer"}
        plan.append((200, fresh))
        token = await impl.async_refresh_token(dict(TOKENS))
        assert token["access_token"] == "dostep-2" and token["refresh_token"] == "odswiez-1" and "expires_at" in token
        # Google refused the refresh token: a new sign-in („Połącz ponownie” in Smart Service HA).
        plan.append((400, {"blad": "invalid_grant"}))
        with pytest.raises(OAuth2TokenRequestReauthError):
            await impl.async_refresh_token(dict(TOKENS))
        # The key not known: no screen, retried; Smart Service HA sees it and renews the key.
        plan.append((401, {}))
        with pytest.raises(OAuth2TokenRequestConnectionError):
            await impl.async_refresh_token(dict(TOKENS))
        assert dysk._state(hass)["klucz_niewazny"] is True
        plan.append((403, {"blad": "konto_wylaczone"}))
        with pytest.raises(OAuth2TokenRequestConnectionError):
            await impl.async_refresh_token(dict(TOKENS))
        assert dysk._state(hass)["konto_wylaczone"] is True
        plan.append((503, {}))
        with pytest.raises(OAuth2TokenRequestConnectionError):
            await impl.async_refresh_token(dict(TOKENS))
        return True

    assert with_panel({"/oauth/dysk/odswiez": odswiez}, test, monkeypatch)
