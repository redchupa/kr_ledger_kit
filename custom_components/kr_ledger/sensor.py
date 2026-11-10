"""Summary sensors: today / this month spending, income, last transaction, review queue."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import KrLedgerConfigEntry
from .const import DOMAIN, NAME, SIGNAL_UPDATED, VERSION
from .engine.store import LedgerStore


def _month_range(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, nxt - timedelta(days=1)


def _sum(totals: dict[str, dict[str, float]], key: str) -> int:
    return int(sum(day.get(key, 0) for day in totals.values()))


def _today_expense(store: LedgerStore, today: date) -> tuple[Any, dict]:
    totals = store.daily_totals(today, today)
    return _sum(totals, "net_expense"), {"count": int(sum(d["count"] for d in totals.values()))}


def _month_expense(store: LedgerStore, today: date) -> tuple[Any, dict]:
    start, end = _month_range(today)
    totals = store.daily_totals(start, end)
    cats = {c["category"]: int(c["total"]) for c in store.category_totals(start, end)}
    foreign = {f["currency"]: round(f["total"], 2) for f in store.foreign_totals(start, end)}
    return _sum(totals, "net_expense"), {"categories": cats, "foreign": foreign, "refund": _sum(totals, "refund")}


def _month_income(store: LedgerStore, today: date) -> tuple[Any, dict]:
    start, end = _month_range(today)
    return _sum(store.daily_totals(start, end), "income"), {}


def _last_tx(store: LedgerStore, today: date) -> tuple[Any, dict]:
    tx = store.last_transaction()
    if not tx:
        return None, {}
    keys = ("kind", "merchant", "category", "account_label", "currency", "occurred_at", "id")
    return tx["amount"], {k: tx.get(k) for k in keys}


def _unparsed(store: LedgerStore, today: date) -> tuple[Any, dict]:
    return store.count_raw("unparsed"), {}


@dataclass(frozen=True, kw_only=True)
class LedgerSensorDescription(SensorEntityDescription):
    value_fn: Callable[[LedgerStore, date], tuple[Any, dict]]


SENSORS: tuple[LedgerSensorDescription, ...] = (
    LedgerSensorDescription(key="today_expense", translation_key="today_expense", icon="mdi:cash-minus",
                            device_class=SensorDeviceClass.MONETARY, native_unit_of_measurement="KRW",
                            suggested_display_precision=0, value_fn=_today_expense),
    LedgerSensorDescription(key="month_expense", translation_key="month_expense", icon="mdi:calendar-month",
                            device_class=SensorDeviceClass.MONETARY, native_unit_of_measurement="KRW",
                            suggested_display_precision=0, value_fn=_month_expense),
    LedgerSensorDescription(key="month_income", translation_key="month_income", icon="mdi:cash-plus",
                            device_class=SensorDeviceClass.MONETARY, native_unit_of_measurement="KRW",
                            suggested_display_precision=0, value_fn=_month_income),
    LedgerSensorDescription(key="last_transaction", translation_key="last_transaction", icon="mdi:receipt-text",
                            native_unit_of_measurement=None, value_fn=_last_tx),
    LedgerSensorDescription(key="unparsed", translation_key="unparsed", icon="mdi:help-box-multiple",
                            value_fn=_unparsed),
)  # fmt: skip


async def async_setup_entry(hass: HomeAssistant, entry: KrLedgerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(LedgerSensor(entry, desc) for desc in SENSORS)


class LedgerSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: KrLedgerConfigEntry, description: LedgerSensorDescription) -> None:
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="kr_ledger_kit",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="homeassistant://kr-ledger",
        )
        self._extra: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATED, self._schedule_refresh))
        await self._refresh()

    @callback
    def _schedule_refresh(self) -> None:
        self.hass.async_create_task(self._refresh(), eager_start=True)

    async def _refresh(self) -> None:
        store = self._entry.runtime_data.store
        today = dt_util.now().date()
        value, extra = await self.hass.async_add_executor_job(self.entity_description.value_fn, store, today)
        self._attr_native_value = value
        self._extra = extra
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._extra
