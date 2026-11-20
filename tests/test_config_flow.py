"""The entry's form: no field for a person; the key only from Smart Service HA (an extra field not drawn)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from custom_components.smartservice_dysk.config_flow import SCHEMA, SmartServiceDyskFlow

KEY = "k" * 32
ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "smartservice_dysk"
SENTENCE = "Połączysz go w Pomoc i konto → Kopia zapasowa."


def flow() -> SmartServiceDyskFlow:
    made = SmartServiceDyskFlow()
    made.flow_id, made.handler, made.context = "f1", "smartservice_dysk", {"source": "user"}

    async def unique(*_args: Any, **_kwargs: Any) -> None:
        return None

    made.async_set_unique_id = unique  # type: ignore[method-assign]
    made._abort_if_unique_id_configured = lambda *a, **k: None  # type: ignore[method-assign]
    return made


def step(user_input: dict[str, Any] | None) -> Any:
    return asyncio.run(flow().async_step_user(user_input))


def test_the_form_draws_no_field() -> None:
    shown = step(None)
    assert shown["type"] == "form" and shown["step_id"] == "user"
    assert list(shown["data_schema"].schema) == [], "a field drawn for the owner"


def test_the_key_from_smart_service_ha_passes_as_an_extra_field() -> None:
    assert SCHEMA({"klucz": KEY}) == {"klucz": KEY}
    made = step({"klucz": KEY})
    assert made["type"] == "create_entry" and made["data"] == {"klucz": KEY}


def test_a_person_submitting_the_form_gets_the_sentence_and_no_entry() -> None:
    for given in ({}, {"klucz": "krotki"}, {"klucz": 5}):
        ended = step(given)
        assert ended["type"] == "abort" and ended["reason"] == "polacz_w_smart_service"


def test_reconfigure_also_without_a_field() -> None:
    made = flow()
    made.context = {"source": "reconfigure", "entry_id": "E1"}
    shown = asyncio.run(made.async_step_reconfigure(None))
    assert shown["type"] == "form" and list(shown["data_schema"].schema) == []
    assert asyncio.run(made.async_step_reconfigure({}))["reason"] == "polacz_w_smart_service"
    entry = SimpleNamespace(entry_id="E1")
    saved: list[Any] = []
    made._get_reconfigure_entry = lambda: entry  # type: ignore[method-assign]
    made.async_update_reload_and_abort = lambda e, data: saved.append((e, data)) or {"type": "abort"}  # type: ignore[method-assign]
    asyncio.run(made.async_step_reconfigure({"klucz": KEY}))
    assert saved == [(entry, {"klucz": KEY})]


def test_the_words_say_where_to_connect_and_no_key_field() -> None:
    for name in ("strings.json", "translations/en.json", "translations/pl.json"):
        words = json.loads((ROOT / name).read_text(encoding="utf-8"))["config"]
        assert SENTENCE in words["abort"]["polacz_w_smart_service"]
        for key in ("user", "reconfigure"):
            assert SENTENCE in words["step"][key]["description"]
            assert "data" not in words["step"][key], f"{name}: {key} names a field"
