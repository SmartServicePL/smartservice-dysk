"""The panel's /oauth/dysk* contract (and Google's revoke address) as a stand-in without a network.

A ClientSession-like object hands each POST to an aiohttp handler in the same process: no socket is opened
(Home Assistant's test plugin blocks them). The handlers get a request with what they read - path, host,
headers, the JSON or form body - and answer with web.json_response as a real panel would."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
import json
from typing import Any
from urllib.parse import parse_qsl

from aiohttp import ClientConnectionError, web
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

BASE = "http://panel.test"

Handler = Callable[[Any], Awaitable[web.StreamResponse]]


class Request:
    """What a handler reads from the request."""

    def __init__(self, url: URL, data: Any, headers: Mapping[str, str] | None) -> None:
        self.path = url.path
        self.host = url.raw_authority
        self.headers = CIMultiDictProxy(CIMultiDict(headers or {}))
        self._data = data

    async def json(self) -> Any:
        if isinstance(self._data, bytes | str):
            return json.loads(self._data) if self._data else {}
        return dict(self._data or {})

    async def post(self) -> dict[str, str]:
        if isinstance(self._data, bytes | str):
            text = self._data.decode() if isinstance(self._data, bytes) else self._data
            return dict(parse_qsl(text))
        return {str(key): str(value) for key, value in dict(self._data or {}).items()}


class _Content:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]


class Response:
    """The answer as the client reads it (status, headers, a body read once)."""

    def __init__(self, answer: web.StreamResponse) -> None:
        self.status = answer.status
        self.headers = CIMultiDictProxy(CIMultiDict(answer.headers))
        body = getattr(answer, "body", b"")
        self.content = _Content(body if isinstance(body, bytes) else b"")


class _Call:
    def __init__(self, session: StandIn, url: str, data: Any, headers: Mapping[str, str] | None) -> None:
        self._session, self._url, self._data, self._headers = session, URL(url), data, headers

    async def __aenter__(self) -> Response:
        if self._session.offline:
            raise ClientConnectionError("brak połączenia")
        handler = self._session.routes.get(self._url.path)
        answer = await handler(Request(self._url, self._data, self._headers)) if handler else web.Response(status=404)
        return Response(answer)

    async def __aexit__(self, *_exc: object) -> None:
        return None


class StandIn:
    """``post(url, ...)`` as aiohttp's ClientSession, served by ``routes`` {path: handler}; ``offline`` - every
    call fails as a connection error."""

    def __init__(self, routes: Mapping[str, Handler] | None = None, *, offline: bool = False) -> None:
        self.routes = dict(routes or {})
        self.offline = offline

    def post(self, url: str, *, data: Any = None, headers: Mapping[str, str] | None = None, **_kwargs: Any) -> _Call:
        return _Call(self, url, data, headers)
