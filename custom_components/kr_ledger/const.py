"""Constants for KR Ledger."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "kr_ledger"
NAME: Final = "KR Ledger"
VERSION: Final = "0.2.1"

CONF_SENSORS: Final = "notification_sensors"
CONF_OWNERS: Final = "owner_names"
CONF_IMPORT_DAYS: Final = "import_days"
CONF_EXTRA_PACKAGES: Final = "extra_packages"
CONF_DEDUPE_MINUTES: Final = "dedupe_minutes"
CONF_RAW_RETENTION_DAYS: Final = "raw_retention_days"

DEFAULT_IMPORT_DAYS: Final = 10
DEFAULT_DEDUPE_MINUTES: Final = 5
DEFAULT_RAW_RETENTION_DAYS: Final = 90

DB_DIR: Final = "kr_ledger"
DB_FILE: Final = "ledger.db"

PANEL_URL_PATH: Final = "kr-ledger"
PANEL_COMPONENT: Final = "kr-ledger-panel"
STATIC_URL: Final = "/kr_ledger_static"

SIGNAL_UPDATED: Final = f"{DOMAIN}_updated"
EVENT_TRANSACTION: Final = f"{DOMAIN}_transaction"

SERVICE_IMPORT_HISTORY: Final = "import_history"
SERVICE_ADD_TRANSACTION: Final = "add_transaction"
SERVICE_DELETE_TRANSACTION: Final = "delete_transaction"
SERVICE_REPROCESS: Final = "reprocess"
