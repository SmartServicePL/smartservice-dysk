# © Smart Service Tczew. Wszelkie prawa zastrzeżone.
"""The panel client against a local stand-in of the panel's /oauth/dysk* contract (no Google, no network)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import importlib.util
from pathlib import Path
import sys
from typing import Any

from aiohttp import ClientSession, web
import pytest

_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "smartservice_dysk" / "panel.py"
_SPEC = importlib.util.spec_from_file_location("smartservice_dysk_panel", _PATH)
assert _SPEC and _SPEC.loader
panel = importlib.util.module_from_spec(_SPEC)
sys.modules["smartservice_dysk_panel"] = panel
_SPEC.loader.exec_module(panel)

TOKENS = {"access_token": "dostep-1", "refresh_token": "odswiez-1", "expires_in": 3599, "token_type": "Bearer",
          "scope": "https://www.googleapis.com/auth/drive.file"}


Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def run(handler: Handler, test: Callable[[str, ClientSession], Awaitable[Any]]) -> Any:
    async def main() -> Any:
        app = web.Application()
        app.router.add_route("POST", "/{tail:.*}", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        try:
            async with ClientSession() as session:
                return await test(f"http://127.0.0.1:{port}", session)
        finally:
            await runner.cleanup()

    return asyncio.run(main())


def answer(status: int, body: object, headers: dict[str, str] | None = None) -> Handler:
    seen: list[tuple[str, str, Any]] = []

    async def handler(request: web.Request) -> web.Response:
        seen.append((request.path, request.headers.get("Authorization", ""), await request.json()))
        return web.json_response(body, status=status, headers=headers)

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


def test_p0_key_with_the_installation_code() -> None:
    handler = answer(200, {"klucz": "klucz-dysku"})
    key = run(handler, lambda base, s: panel.PanelDysk.new_key(s, "KOD-INST", base=base))
    assert key == "klucz-dysku"
    assert handler.seen == [("/oauth/dysk/klucz", "Bearer KOD-INST", {})]


def test_p1_session_only_to_the_panels_own_start_address() -> None:
    def start(base: str) -> Callable[[web.Request], Awaitable[web.Response]]:
        return answer(200, {"adres": f"{base}/oauth/dysk/start?s=abc", "odbior": "odb-1", "wazna_s": 600})

    async def test(base: str, s: ClientSession) -> Any:
        return await panel.PanelDysk(s, "klucz", base=base).start()

    # The stand-in does not know its port before it runs: build the answer from the request.
    async def handler(request: web.Request) -> web.Response:
        base = f"http://{request.host}"
        return await start(base)(request)

    result = run(handler, test)
    assert result.collect == "odb-1" and result.valid_s == 600 and result.address.endswith("/oauth/dysk/start?s=abc")
    # An address elsewhere (another host) is never opened.
    bad = answer(200, {"adres": "https://zly.example/oauth/dysk/start?s=abc", "odbior": "o", "wazna_s": 600})
    with pytest.raises(panel.PanelError):
        run(bad, test)


def test_p3_states_and_tokens_once() -> None:
    async def collect(base: str, s: ClientSession) -> Any:
        return await panel.PanelDysk(s, "klucz", base=base).result("odb-1")

    assert run(answer(200, {"stan": "czeka"}), collect).state == "czeka"
    done = run(answer(200, {"stan": "gotowe", "tokeny": TOKENS}), collect)
    assert done.state == "gotowe" and done.tokens == TOKENS
    assert run(answer(200, {"stan": "odmowa"}), collect).state == "odmowa"
    with pytest.raises(panel.SessionExpired):
        run(answer(410, {"stan": "wygasla"}), collect)
    # Tokens without expires_in or without a refresh token are never passed on.
    for broken in ({**TOKENS, "expires_in": "3599"}, {k: v for k, v in TOKENS.items() if k != "refresh_token"},
                   {**TOKENS, "token_type": "MAC"}):
        with pytest.raises(panel.PanelError):
            run(answer(200, {"stan": "gotowe", "tokeny": broken}), collect)


def test_p4_refresh_and_its_errors() -> None:
    async def refresh(base: str, s: ClientSession) -> Any:
        return await panel.PanelDysk(s, "klucz", base=base).refresh("odswiez-1")

    fresh = {k: v for k, v in TOKENS.items() if k != "refresh_token"}
    handler = answer(200, fresh)
    assert run(handler, refresh) == fresh
    assert handler.seen == [("/oauth/dysk/odswiez", "Bearer klucz", {"refresh_token": "odswiez-1"})]
    with pytest.raises(panel.GrantRevoked):
        run(answer(400, {"blad": "invalid_grant"}), refresh)
    with pytest.raises(panel.KeyInvalid):
        run(answer(401, {}), refresh)
    with pytest.raises(panel.AccountDisabled):
        run(answer(403, {"blad": "konto_wylaczone"}), refresh)
    with pytest.raises(panel.PanelUnavailable) as busy:
        run(answer(503, {"blad": "x"}, {"Retry-After": "60"}), refresh)
    assert busy.value.retry_after == 60
    with pytest.raises(panel.PanelUnavailable):
        run(answer(429, {}, {"Retry-After": "5"}), refresh)


def test_no_connection_is_unavailable_and_errors_carry_no_secret() -> None:
    async def test() -> None:
        async with ClientSession() as s:
            await panel.PanelDysk(s, "tajny-klucz", base="http://127.0.0.1:9").refresh("tajny-token")

    with pytest.raises(panel.PanelUnavailable) as err:
        asyncio.run(test())
    assert "tajny" not in str(err.value)
    # A too long refresh token is not even sent.
    with pytest.raises(panel.GrantRevoked):
        asyncio.run(panel.PanelDysk(None, "k").refresh("x" * 513))  # type: ignore[arg-type]
