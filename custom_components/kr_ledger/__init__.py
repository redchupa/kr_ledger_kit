"""KR Ledger: a household ledger built from Android financial notifications."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import voluptuous as vol
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, ServiceCall, ServiceResponse, State, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEDUPE_MINUTES,
    CONF_EXTRA_PACKAGES,
    CONF_IMPORT_DAYS,
    CONF_OWNERS,
    CONF_RAW_RETENTION_DAYS,
    CONF_SENSORS,
    DB_DIR,
    DB_FILE,
    DEFAULT_DEDUPE_MINUTES,
    DEFAULT_RAW_RETENTION_DAYS,
    DOMAIN,
    EVENT_TRANSACTION,
    PANEL_COMPONENT,
    PANEL_URL_PATH,
    SERVICE_ADD_TRANSACTION,
    SERVICE_DELETE_TRANSACTION,
    SERVICE_IMPORT_HISTORY,
    SERVICE_REPROCESS,
    SIGNAL_UPDATED,
    STATIC_URL,
    VERSION,
)
from .engine import RawNotification
from .engine.android import raws_from_attributes
from .engine.processor import LedgerProcessor, Outcome
from .engine.store import LedgerStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class KrLedgerData:
    store: LedgerStore
    processor: LedgerProcessor
    sensors: list[str]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


type KrLedgerConfigEntry = ConfigEntry[KrLedgerData]


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.replace("\n", ",").split(",") if v.strip()]


def raws_from_state(state: State, previous: State | None = None) -> list[RawNotification]:
    """Notifications in a last-notification or active-notification state that ``previous`` didn't have."""
    return raws_from_attributes(
        state.attributes,
        state.entity_id,
        dt_util.get_default_time_zone(),
        previous.attributes if previous is not None else None,
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    from . import websocket_api

    websocket_api.async_register(hass)
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: KrLedgerConfigEntry) -> bool:
    store = LedgerStore(Path(hass.config.path(DB_DIR)) / DB_FILE)
    await hass.async_add_executor_job(store.open)
    processor = LedgerProcessor(
        store,
        owners=_split(entry.options.get(CONF_OWNERS)),
        extra_packages=_split(entry.options.get(CONF_EXTRA_PACKAGES)),
        dedupe_minutes=float(entry.options.get(CONF_DEDUPE_MINUTES, DEFAULT_DEDUPE_MINUTES)),
    )
    sensors = list(entry.data.get(CONF_SENSORS, []))
    data = KrLedgerData(store=store, processor=processor, sensors=sensors)
    entry.runtime_data = data

    @callback
    def _state_changed(event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        old = event.data["old_state"]
        if new is None:
            return
        # Only notifications that are new compared to the previous state; anything
        # seen before (e.g. re-reported after a restart) is also caught by fingerprint.
        raws = raws_from_state(new, old)
        if raws:
            hass.async_create_task(_async_process(hass, entry, raws, live=True), eager_start=True)

    if sensors:
        entry.async_on_unload(async_track_state_change_event(hass, sensors, _state_changed))

        async def _scan_current() -> None:
            # Notifications already in the shade when we start (e.g. a newly added
            # active-notification sensor). Fingerprints keep this idempotent.
            raws: list[RawNotification] = []
            for entity_id in sensors:
                if (state := hass.states.get(entity_id)) is not None:
                    raws.extend(raws_from_state(state))
            if raws:
                await _async_process(hass, entry, sorted(raws, key=lambda r: r.post_time), live=False)

        entry.async_create_background_task(hass, _scan_current(), f"{DOMAIN}_scan_current")

    async def _midnight(now: datetime) -> None:
        retention = int(entry.options.get(CONF_RAW_RETENTION_DAYS, DEFAULT_RAW_RETENTION_DAYS))
        await hass.async_add_executor_job(store.purge_raw, dt_util.now() - timedelta(days=retention))
        async_dispatcher_send(hass, SIGNAL_UPDATED)

    entry.async_on_unload(async_track_time_change(hass, _midnight, hour=0, minute=0, second=5))
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_register_panel(hass)

    days = int(entry.data.get(CONF_IMPORT_DAYS, 0) or 0)
    if days and await hass.async_add_executor_job(store.get_meta, "history_imported") is None:

        async def _import_later() -> None:
            count = await async_import_history(hass, entry, days)
            await hass.async_add_executor_job(store.set_meta, "history_imported", dt_util.now().isoformat())
            _LOGGER.info("KR Ledger imported %s notifications from recorder history", count)

        entry.async_create_background_task(hass, _import_later(), f"{DOMAIN}_import_history")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KrLedgerConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
        hass.data.get(DOMAIN, {}).pop("panel", None)
        await hass.async_add_executor_job(entry.runtime_data.store.close)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: KrLedgerConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_panel(hass: HomeAssistant) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get("static"):
        path = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(path), cache_headers=False)])
        domain_data["static"] = True
    if domain_data.get("panel"):
        return
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title="가계부",
        sidebar_icon="mdi:wallet-outline",
        module_url=f"{STATIC_URL}/kr-ledger-panel.js?v={VERSION}",
        require_admin=False,
        config={},
    )
    domain_data["panel"] = True


def get_entry(hass: HomeAssistant) -> KrLedgerConfigEntry:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry
    raise ServiceValidationError("KR Ledger is not set up")


async def _async_process(hass: HomeAssistant, entry: KrLedgerConfigEntry, raws: list[RawNotification], live: bool) -> list[Outcome]:
    data = entry.runtime_data
    async with data.lock:
        outcomes = await hass.async_add_executor_job(lambda: [data.processor.process(r) for r in raws])
    changed = False
    for out in outcomes:
        if out.transaction_id is None and out.schedule_id is None and out.raw_id is None:
            continue
        changed = True
        if live and out.new_transaction and out.transaction:
            tx = out.transaction
            hass.bus.async_fire(
                EVENT_TRANSACTION,
                {
                    "id": tx["id"],
                    "kind": tx["kind"],
                    "amount": tx["amount"],
                    "currency": tx["currency"],
                    "merchant": tx["merchant"],
                    "category": tx["category"],
                    "account": tx["account_label"],
                    "occurred_at": tx["occurred_at"],
                },
            )
    if changed:
        async_dispatcher_send(hass, SIGNAL_UPDATED)
    return outcomes


async def async_import_history(hass: HomeAssistant, entry: KrLedgerConfigEntry, days: int) -> int:
    """Replay recorder history of the notification sensors (idempotent)."""
    from homeassistant.components.recorder import get_instance, history

    start = dt_util.utcnow() - timedelta(days=days)
    raws: list[RawNotification] = []
    for entity_id in entry.runtime_data.sensors:
        states = await get_instance(hass).async_add_executor_job(
            lambda eid=entity_id: history.state_changes_during_period(
                hass, start, None, eid, no_attributes=False, include_start_time_state=True
            )
        )
        previous: State | None = None
        for state in states.get(entity_id, []):
            raws.extend(raws_from_state(state, previous))
            previous = state
    raws.sort(key=lambda r: r.post_time)
    await _async_process(hass, entry, raws, live=False)
    return len(raws)


# ---------------------------------------------------------------------- services

ADD_SCHEMA = vol.Schema(
    {
        vol.Required("amount"): vol.Coerce(float),
        vol.Optional("kind", default="expense"): vol.In(["expense", "income", "transfer", "refund"]),
        vol.Optional("merchant"): cv.string,
        vol.Optional("category"): cv.string,
        vol.Optional("memo"): cv.string,
        vol.Optional("account"): cv.string,
        vol.Optional("when"): cv.datetime,
    }
)


def _register_services(hass: HomeAssistant) -> None:
    async def _import(call: ServiceCall) -> ServiceResponse:
        entry = get_entry(hass)
        count = await async_import_history(hass, entry, int(call.data.get("days", 10)))
        return {"notifications": count}

    async def _add(call: ServiceCall) -> ServiceResponse:
        entry = get_entry(hass)
        when = call.data.get("when") or dt_util.now()
        when = dt_util.as_local(when if when.tzinfo else when.replace(tzinfo=dt_util.get_default_time_zone()))
        fields = {
            "occurred_at": when,
            "kind": call.data["kind"],
            "amount": str(call.data["amount"]).removesuffix(".0"),
            "merchant": call.data.get("merchant"),
            "category": call.data.get("category"),
            "memo": call.data.get("memo"),
            "account_label": call.data.get("account"),
        }
        tx_id = await hass.async_add_executor_job(lambda: entry.runtime_data.processor.add_manual(**fields))
        async_dispatcher_send(hass, SIGNAL_UPDATED)
        return {"id": tx_id}

    async def _delete(call: ServiceCall) -> None:
        entry = get_entry(hass)
        await hass.async_add_executor_job(lambda: entry.runtime_data.store.update_transaction(int(call.data["id"]), deleted=1))
        async_dispatcher_send(hass, SIGNAL_UPDATED)

    async def _reprocess(call: ServiceCall) -> ServiceResponse:
        entry = get_entry(hass)
        async with entry.runtime_data.lock:
            fixed = await hass.async_add_executor_job(entry.runtime_data.processor.reprocess_unparsed)
        async_dispatcher_send(hass, SIGNAL_UPDATED)
        return {"fixed": fixed}

    hass.services.async_register(
        DOMAIN, SERVICE_IMPORT_HISTORY, _import,
        schema=vol.Schema({vol.Optional("days", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=365))}),
        supports_response=SupportsResponse.OPTIONAL,
    )  # fmt: skip
    hass.services.async_register(DOMAIN, SERVICE_ADD_TRANSACTION, _add, schema=ADD_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_DELETE_TRANSACTION, _delete, schema=vol.Schema({vol.Required("id"): vol.Coerce(int)}))
    hass.services.async_register(DOMAIN, SERVICE_REPROCESS, _reprocess, supports_response=SupportsResponse.OPTIONAL)
