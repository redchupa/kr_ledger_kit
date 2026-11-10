"""WebSocket API used by the sidebar panel."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_UPDATED
from .engine.ledger import DEFAULT_CATEGORIES


def _entry(hass: HomeAssistant):
    from . import get_entry

    return get_entry(hass)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, nxt - timedelta(days=1)


@callback
def async_register(hass: HomeAssistant) -> None:
    for handler in (
        ws_month, ws_transactions, ws_update, ws_delete, ws_add, ws_unparsed, ws_dismiss,
        ws_accounts, ws_update_account, ws_meta,
    ):  # fmt: skip
        websocket_api.async_register_command(hass, handler)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/month", vol.Required("year"): int, vol.Required("month"): int})
@websocket_api.async_response
async def ws_month(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    store = _entry(hass).runtime_data.store
    start, end = _month_bounds(msg["year"], msg["month"])

    def _load() -> dict:
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": store.daily_totals(start, end),
            "categories": store.category_totals(start, end),
            "foreign": store.foreign_totals(start, end),
            "schedules": store.list_schedules(start, end + timedelta(days=31)),
            "transactions": store.list_transactions(start, end),
            "unparsed": store.count_raw("unparsed"),
        }

    connection.send_result(msg["id"], await hass.async_add_executor_job(_load))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/transactions", vol.Required("start"): str, vol.Required("end"): str})
@websocket_api.async_response
async def ws_transactions(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    store = _entry(hass).runtime_data.store
    start, end = date.fromisoformat(msg["start"]), date.fromisoformat(msg["end"])
    connection.send_result(msg["id"], await hass.async_add_executor_job(store.list_transactions, start, end))


TX_FIELDS = {
    vol.Optional("kind"): vol.In(["expense", "income", "transfer", "refund"]),
    vol.Optional("amount"): vol.Coerce(float),
    vol.Optional("merchant"): vol.Any(None, str),
    vol.Optional("category"): vol.Any(None, str),
    vol.Optional("memo"): vol.Any(None, str),
    vol.Optional("account_label"): vol.Any(None, str),
    vol.Optional("occurred_at"): str,
}


def _clean_fields(msg: dict[str, Any]) -> dict[str, Any]:
    fields = {k: msg[k] for k in ("kind", "amount", "merchant", "category", "memo", "account_label", "occurred_at") if k in msg}
    if "amount" in fields:
        fields["amount"] = str(fields["amount"]).removesuffix(".0")
    if "occurred_at" in fields:
        when = datetime.fromisoformat(fields["occurred_at"])
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt_util.get_default_time_zone())
        fields["occurred_at"] = dt_util.as_local(when)
    for key in ("merchant", "category", "memo", "account_label"):
        if key in fields and isinstance(fields[key], str):
            fields[key] = fields[key].strip() or None
    return fields


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/transaction/update", vol.Required("tx_id"): int, **TX_FIELDS})
@websocket_api.async_response
async def ws_update(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    processor = _entry(hass).runtime_data.processor
    row = await hass.async_add_executor_job(processor.edit, msg["tx_id"], _clean_fields(msg))
    if row is None:
        connection.send_error(msg["id"], "not_found", "transaction not found")
        return
    async_dispatcher_send(hass, SIGNAL_UPDATED)
    connection.send_result(msg["id"], row)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/transaction/delete", vol.Required("tx_id"): int})
@websocket_api.async_response
async def ws_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    store = _entry(hass).runtime_data.store
    await hass.async_add_executor_job(lambda: store.update_transaction(msg["tx_id"], deleted=1, edited=1))
    async_dispatcher_send(hass, SIGNAL_UPDATED)
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/transaction/add", vol.Required("amount"): vol.Coerce(float), vol.Optional("raw_id"): int, **TX_FIELDS}
)
@websocket_api.async_response
async def ws_add(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    data = _entry(hass).runtime_data
    fields = _clean_fields(msg)
    fields.setdefault("kind", "expense")
    fields.setdefault("occurred_at", dt_util.now())
    raw_id = msg.get("raw_id")

    def _do() -> int:
        tx_id = data.processor.add_manual(raw_ids=[raw_id] if raw_id else [], **fields)
        if raw_id:
            data.store.update_raw(raw_id, transaction_id=tx_id, dismissed=1, reason="entered manually")
        return tx_id

    tx_id = await hass.async_add_executor_job(_do)
    async_dispatcher_send(hass, SIGNAL_UPDATED)
    connection.send_result(msg["id"], {"id": tx_id})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/unparsed"})
@websocket_api.async_response
async def ws_unparsed(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    store = _entry(hass).runtime_data.store
    connection.send_result(msg["id"], await hass.async_add_executor_job(store.list_raw, "unparsed"))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/unparsed/dismiss", vol.Required("raw_id"): int})
@websocket_api.async_response
async def ws_dismiss(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    store = _entry(hass).runtime_data.store
    await hass.async_add_executor_job(lambda: store.update_raw(msg["raw_id"], dismissed=1))
    async_dispatcher_send(hass, SIGNAL_UPDATED)
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/accounts"})
@websocket_api.async_response
async def ws_accounts(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    store = _entry(hass).runtime_data.store
    connection.send_result(msg["id"], await hass.async_add_executor_job(store.list_accounts))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/account/update",
        vol.Required("account_id"): int,
        vol.Optional("name"): str,
        vol.Optional("owner_type"): vol.In(["personal", "business"]),
        vol.Optional("include"): bool,
    }
)
@websocket_api.async_response
async def ws_update_account(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    store = _entry(hass).runtime_data.store
    fields = {k: msg[k] for k in ("name", "owner_type", "include") if k in msg}
    if "include" in fields:
        fields["include"] = int(fields["include"])
    await hass.async_add_executor_job(lambda: store.update_account(msg["account_id"], **fields))
    async_dispatcher_send(hass, SIGNAL_UPDATED)
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/meta"})
@websocket_api.async_response
async def ws_meta(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    store = _entry(hass).runtime_data.store
    used = await hass.async_add_executor_job(store.list_categories)
    defaults = [name for name, _ in DEFAULT_CATEGORIES]
    categories = defaults + [c for c in used if c not in defaults and c not in ("이체", "카드대금", "수입")]
    connection.send_result(msg["id"], {"categories": categories, "special": ["이체", "카드대금", "수입"]})
