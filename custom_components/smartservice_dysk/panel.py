"""The Smart Service panel's Dysk Google points (/oauth/dysk*), the client side.

The panel holds the Google client's secret; the home holds the tokens. This module only talks to the panel: it never
logs, keeps or returns a token anywhere but to its caller, and it has no Home Assistant import (tested on its own).

P0 POST /oauth/dysk/klucz   Bearer <installation code>  -> {"klucz"}            (Smart Service HA only)
P1 POST /oauth/dysk/sesja   Bearer <Dysk key>, {}       -> {"adres", "odbior", "wazna_s"}
P3 POST /oauth/dysk/wynik   Bearer <Dysk key>, {"odbior"} -> {"stan": czeka|gotowe|odmowa|blad, "tokeny"?}; 410 wygasla
P4 POST /oauth/dysk/odswiez Bearer <Dysk key>, {"refresh_token"} -> {"access_token", "expires_in", ...}
Errors (every point): 401 key unknown, 403 {"blad": "konto_wylaczone"}, 429 / 503 with Retry-After; P4 400
{"blad": "invalid_grant"}.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any

import aiohttp

PANEL = "https://panel.smartservice.net.pl"
P0 = "/oauth/dysk/klucz"
P1 = "/oauth/dysk/sesja"
P3 = "/oauth/dysk/wynik"
P4 = "/oauth/dysk/odswiez"
# P3 waits up to 25 s on the panel's side; a little more for the network.
WAIT_S = 35
REQUEST_S = 15
MAX_REFRESH_TOKEN = 512
MAX_ANSWER = 64 * 1024
TOKEN_KEYS = ("access_token", "refresh_token", "expires_in", "token_type", "scope")


class PanelError(Exception):
    """Any answer the caller cannot use; the text never carries a token or a key."""


class PanelUnavailable(PanelError):
    """No answer, 5xx or 429: try again later (``retry_after`` seconds when the panel said)."""

    def __init__(self, reason: str, retry_after: int | None = None) -> None:
        super().__init__(reason)
        self.retry_after = retry_after


class KeyInvalid(PanelError):
    """401: the Dysk key is not known (Smart Service HA takes a new one with P0)."""


class AccountDisabled(PanelError):
    """403 konto_wylaczone: no retries, the reason is shown."""


class SessionExpired(PanelError):
    """410: the session is over (10 min, another account, or already collected)."""


class GrantRevoked(PanelError):
    """P4 400 invalid_grant: Google no longer accepts the refresh token - connect again."""


@dataclass(frozen=True)
class Session:
    """P1: the address the browser opens (the panel sends it on to Google) and the collection id."""

    address: str
    collect: str
    valid_s: int


@dataclass(frozen=True)
class Result:
    """P3: ``czeka`` (ask again), ``gotowe`` (tokens, given once), ``odmowa`` or ``blad``."""

    state: str
    tokens: dict[str, Any] | None = None


def _retry_after(headers: Mapping[str, str]) -> int | None:
    value = headers.get("Retry-After", "")
    return int(value) if value.isdigit() else None


def _tokens(raw: object, *, refresh: bool) -> dict[str, Any]:
    """The tokens exactly as the contract gives them; anything else is an error (never passed on)."""

    if not isinstance(raw, Mapping):
        raise PanelError("odpowiedź panelu bez tokenów")
    access = raw.get("access_token")
    expires = raw.get("expires_in")
    if not isinstance(access, str) or not access or isinstance(expires, bool) or not isinstance(expires, int):
        raise PanelError("odpowiedź panelu bez tokenów")
    if raw.get("token_type", "Bearer") != "Bearer":
        raise PanelError("odpowiedź panelu bez tokenów")
    tokens = {key: raw[key] for key in TOKEN_KEYS if key in raw}
    if refresh:
        given = raw.get("refresh_token")
        if given is not None and (not isinstance(given, str) or not given):
            raise PanelError("odpowiedź panelu bez tokenów")
    elif not isinstance(raw.get("refresh_token"), str) or not raw.get("refresh_token"):
        raise PanelError("odpowiedź panelu bez tokenów")
    return tokens


class PanelDysk:
    """One home's Dysk key against the panel."""

    def __init__(self, session: aiohttp.ClientSession, key: str, *, base: str = PANEL) -> None:
        self._session = session
        self._key = key
        self._base = base.rstrip("/")

    async def _post(
        self, path: str, body: Mapping[str, object], *, bearer: str, seconds: float
    ) -> tuple[int, dict[str, Any], Mapping[str, str]]:
        try:
            async with self._session.post(
                f"{self._base}{path}",
                data=json.dumps(dict(body)),
                headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=seconds),
                allow_redirects=False,
            ) as response:
                raw = await response.content.read(MAX_ANSWER + 1)
                status, headers = response.status, response.headers
        except (TimeoutError, aiohttp.ClientError) as err:
            raise PanelUnavailable("brak połączenia z panelem Smart Service") from err
        if len(raw) > MAX_ANSWER:
            raise PanelUnavailable("za duża odpowiedź panelu")
        try:
            answer = json.loads(raw) if raw else {}
        except ValueError:
            answer = {}
        if not isinstance(answer, dict):
            answer = {}
        if status in (429,) or status >= 500:
            raise PanelUnavailable(f"panel Smart Service: {status}", _retry_after(headers))
        if status == 401:
            raise KeyInvalid("klucz Dysku nieznany")
        if status == 403:
            raise AccountDisabled("konto Smart Service wyłączone")
        if status == 410:
            raise SessionExpired("sesja wygasła")
        return status, answer, headers

    @staticmethod
    async def new_key(session: aiohttp.ClientSession, code: str, *, base: str = PANEL) -> str:
        """P0 (Smart Service HA only - it has the installation code): a Dysk key, given once."""

        status, answer, _headers = await PanelDysk(session, "", base=base)._post(
            P0, {}, bearer=code, seconds=REQUEST_S
        )
        key = answer.get("klucz")
        if status != 200 or not isinstance(key, str) or not key:
            raise PanelError("panel nie wydał klucza Dysku")
        return key

    async def start(self) -> Session:
        """P1: a new session; the address goes to the owner's browser only."""

        status, answer, _headers = await self._post(P1, {}, bearer=self._key, seconds=REQUEST_S)
        address, collect, valid = answer.get("adres"), answer.get("odbior"), answer.get("wazna_s")
        if (
            status != 200
            or not isinstance(address, str)
            or not address.startswith(f"{self._base}/oauth/dysk/start?")
            or not isinstance(collect, str)
            or not collect
            or isinstance(valid, bool)
            or not isinstance(valid, int)
        ):
            raise PanelError("panel nie rozpoczął połączenia z Dyskiem Google")
        return Session(address=address, collect=collect, valid_s=valid)

    async def result(self, collect: str) -> Result:
        """P3: one wait (up to 25 s on the panel); the tokens come once."""

        status, answer, _headers = await self._post(P3, {"odbior": collect}, bearer=self._key, seconds=WAIT_S)
        state = answer.get("stan")
        if status != 200 or state not in ("czeka", "gotowe", "odmowa", "blad"):
            raise PanelError("nieznana odpowiedź panelu")
        if state == "gotowe":
            return Result(state=state, tokens=_tokens(answer.get("tokeny"), refresh=False))
        return Result(state=state)

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        """P4: a new access token (and a new refresh token when Google gives one); nothing kept on the panel."""

        if not refresh_token or len(refresh_token) > MAX_REFRESH_TOKEN:
            raise GrantRevoked("token odświeżania niepoprawny")
        status, answer, _headers = await self._post(
            P4, {"refresh_token": refresh_token}, bearer=self._key, seconds=REQUEST_S
        )
        if status == 400 and answer.get("blad") == "invalid_grant":
            raise GrantRevoked("Google nie przyjmuje już tego połączenia")
        if status != 200:
            raise PanelError("nieznana odpowiedź panelu")
        return _tokens(answer, refresh=True)
