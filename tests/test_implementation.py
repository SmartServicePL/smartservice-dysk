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
    """Home Assistant's flow manager as the implementation sees it: the external data given (external step done),
    then the next step run (create_entry, or the refusal's abort)."""

    def __init__(self, entries: list[Any], drive: list[Any] | None = None, end: dict | None = None) -> None:
        self.data: dict[str, Any] = {}
        self.configured: list[tuple[str, dict | None]] = []
        self.tasks: list[asyncio.Task] = []
        hass = self

        class Flow:
            async def async_configure(self, *, flow_id: str, user_input: dict | None = None) -> dict:
                hass.configured.append((flow_id, user_input))
                if user_input is not None:
                    return {"type": "external_done", "flow_id": flow_id}
                rejected = any(given and "error" in given for _, given in hass.configured)
                if rejected:
                    return {"type": "abort", "reason": "user_rejected_authorize"}
                return end or {"type": "create_entry"}

        self.config_entries = SimpleNamespace(
            async_entries=lambda domain: {dysk.DOMAIN: entries, "google_drive": drive or []}.get(domain, []),
            flow=Flow(),
        )

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


def test_sign_in_passes_the_tokens_once_and_ends_the_flow_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([{"stan": "czeka"}, {"stan": "gotowe", "tokeny": TOKENS}])
    sessions: list[str] = []

    async def sesja(request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == "Bearer klucz-dysku"
        sessions.append("x")
        return _session(request)

    async def wynik(request: web.Request) -> web.Response:
        assert await request.json() == {"odbior": "odb-1"}
        return web.json_response(next(answers))

    async def test(base: str, _s: ClientSession) -> Any:
        hass = FakeHass([])
        impl = dysk.SmartServiceDyskImplementation(hass, "klucz-dysku", base=base)
        url = await impl.async_generate_authorize_url("flow-1")
        # Home Assistant shows the external step again (a read of the flow): the same address, no new session.
        assert await impl.async_generate_authorize_url("flow-1") == url
        assert dysk._flows(hass)["flow-1"]["stan"] == "czeka"
        await asyncio.gather(*hass.tasks)
        given = hass.configured[0][1]
        assert given is not None
        return url, hass.configured, await impl.async_resolve_external_data(given), dysk._flows(hass)

    routes = {"/oauth/dysk/sesja": sesja, "/oauth/dysk/wynik": wynik}
    url, configured, resolved, flows = with_panel(routes, test, monkeypatch)
    assert url.endswith("/oauth/dysk/start?s=abc")
    assert sessions == ["x"]
    # The tokens once, then the step after the external one - the flow ends here, nothing waits for a browser.
    assert configured == [("flow-1", TOKENS), ("flow-1", None)]
    assert resolved == TOKENS
    assert flows["flow-1"]["stan"] == "gotowe" and "adres" not in flows["flow-1"]


def test_a_refusal_ends_the_flow_as_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def sesja(request: web.Request) -> web.Response:
        return _session(request)

    async def wynik(_request: web.Request) -> web.Response:
        return web.json_response({"stan": "odmowa"})

    async def test(base: str, _s: ClientSession) -> Any:
        hass = FakeHass([])
        await dysk.SmartServiceDyskImplementation(hass, "k", base=base).async_generate_authorize_url("flow-2")
        await asyncio.gather(*hass.tasks)
        return hass.configured, dysk._flows(hass)

    configured, flows = with_panel({"/oauth/dysk/sesja": sesja, "/oauth/dysk/wynik": wynik}, test, monkeypatch)
    assert configured == [("flow-2", {"error": "odmowa"}), ("flow-2", None)]
    assert flows["flow-2"]["stan"] == "odmowa"


def test_a_flow_ending_without_an_entry_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def sesja(request: web.Request) -> web.Response:
        return _session(request)

    async def wynik(_request: web.Request) -> web.Response:
        return web.json_response({"stan": "gotowe", "tokeny": TOKENS})

    async def test(base: str, _s: ClientSession) -> Any:
        hass = FakeHass([], end={"type": "abort", "reason": "already_configured"})
        await dysk.SmartServiceDyskImplementation(hass, "k", base=base).async_generate_authorize_url("flow-3")
        await asyncio.gather(*hass.tasks)
        return dysk._flows(hass)

    flows = with_panel({"/oauth/dysk/sesja": sesja, "/oauth/dysk/wynik": wynik}, test, monkeypatch)
    assert flows["flow-3"]["stan"] == "blad"


def test_ours_lists_only_the_drive_entries_signed_in_through_smart_service() -> None:
    drive = [
        SimpleNamespace(entry_id="E1", unique_id="konto-1", data={"auth_implementation": "smartservice_dysk"}),
        SimpleNamespace(entry_id="E2", unique_id="konto-2", data={"auth_implementation": "google_drive"}),
    ]
    assert dysk._ours(FakeHass([], drive)) == [{"entry_id": "E1", "unique_id": "konto-1"}]


class Connection:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Any]] = []

    def send_result(self, msg_id: int, result: Any) -> None:
        self.sent.append(("result", result))

    def send_error(self, msg_id: int, code: str, message: str) -> None:
        self.sent.append(("error", code))


def test_revoke_failing_at_google_is_an_error_not_a_result(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = SimpleNamespace(entry_id="E1", domain="google_drive",
                            data={"auth_implementation": "smartservice_dysk", "token": {"refresh_token": "odswiez-1"}})
    status = {"code": 503}

    async def revoke(request: web.Request) -> web.Response:
        return web.json_response({}, status=status["code"])

    async def test(base: str, _s: ClientSession) -> Any:
        monkeypatch.setattr(dysk, "REVOKE_URL", f"{base}/revoke")
        hass = FakeHass([])
        hass.config_entries.async_get_entry = lambda entry_id: entry if entry_id == "E1" else None
        handler = dysk.ws_revoke
        while hasattr(handler, "__wrapped__"):  # the command itself, without Home Assistant's decorators
            handler = handler.__wrapped__
        sent = []
        for code in (503, 200, 400):
            status["code"] = code
            connection = Connection()
            await handler(hass, connection, {"id": 1, "entry_id": "E1"})
            sent.append(connection.sent[0])
        connection = Connection()
        await handler(hass, connection, {"id": 1, "entry_id": "E9"})
        sent.append(connection.sent[0])
        return sent

    sent = with_panel({"/revoke": revoke}, test, monkeypatch)
    assert sent == [("error", "revoke_failed"), ("result", {"uniewazniono": True}), ("result", {"uniewazniono": True}),
                    ("error", "not_ours")]


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
