"""Config flow for KR Ledger."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEDUPE_MINUTES,
    CONF_EXTRA_PACKAGES,
    CONF_IMPORT_DAYS,
    CONF_OWNERS,
    CONF_RAW_RETENTION_DAYS,
    CONF_SENSORS,
    DEFAULT_DEDUPE_MINUTES,
    DEFAULT_IMPORT_DAYS,
    DEFAULT_RAW_RETENTION_DAYS,
    DOMAIN,
    NAME,
)

SENSOR_SELECTOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", integration="mobile_app", multiple=True))


def _suggest_sensors(hass) -> list[str]:
    """Pre-select every phone's last-notification and active-notification sensors."""
    suffixes = ("_last_notification", "_active_notification_count")
    return [s.entity_id for s in hass.states.async_all("sensor") if s.entity_id.endswith(suffixes)]


class KrLedgerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_SENSORS):
                errors[CONF_SENSORS] = "no_sensor"
            else:
                return self.async_create_entry(
                    title=NAME,
                    data={CONF_SENSORS: user_input[CONF_SENSORS], CONF_IMPORT_DAYS: int(user_input.get(CONF_IMPORT_DAYS, 0))},
                    options={
                        CONF_OWNERS: user_input.get(CONF_OWNERS, ""),
                        CONF_EXTRA_PACKAGES: "",
                        CONF_DEDUPE_MINUTES: DEFAULT_DEDUPE_MINUTES,
                        CONF_RAW_RETENTION_DAYS: DEFAULT_RAW_RETENTION_DAYS,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_SENSORS, default=_suggest_sensors(self.hass)): SENSOR_SELECTOR,
                vol.Optional(CONF_OWNERS, default=""): selector.TextSelector(),
                vol.Optional(CONF_IMPORT_DAYS, default=DEFAULT_IMPORT_DAYS): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=30, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return KrLedgerOptionsFlow()


class KrLedgerOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        if user_input is not None:
            sensors = user_input.pop(CONF_SENSORS, None)
            if sensors:
                self.hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_SENSORS: sensors})
            return self.async_create_entry(data=user_input)

        opts = entry.options
        schema = vol.Schema(
            {
                vol.Required(CONF_SENSORS, default=entry.data.get(CONF_SENSORS, [])): SENSOR_SELECTOR,
                vol.Optional(CONF_OWNERS, default=opts.get(CONF_OWNERS, "")): selector.TextSelector(),
                vol.Optional(CONF_EXTRA_PACKAGES, default=opts.get(CONF_EXTRA_PACKAGES, "")): selector.TextSelector(),
                vol.Optional(CONF_DEDUPE_MINUTES, default=opts.get(CONF_DEDUPE_MINUTES, DEFAULT_DEDUPE_MINUTES)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=30, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_RAW_RETENTION_DAYS, default=opts.get(CONF_RAW_RETENTION_DAYS, DEFAULT_RAW_RETENTION_DAYS)
                ): selector.NumberSelector(selector.NumberSelectorConfig(min=7, max=3650, step=1, mode=selector.NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
