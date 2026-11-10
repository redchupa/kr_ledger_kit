"""Data models for the notification parser (no Home Assistant dependency)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class Status(StrEnum):
    """Outcome of parsing one notification."""

    TRANSACTION = "transaction"  # money moved
    SCHEDULE = "schedule"  # upcoming bill / payment notice
    IGNORED = "ignored"  # financial app, but not a money movement (news, ads, OTP)
    UNPARSED = "unparsed"  # looks like money movement but no rule matched
    DROPPED = "dropped"  # not financial at all (personal SMS etc.) - never stored


class Direction(StrEnum):
    OUT = "out"
    IN = "in"


class Method(StrEnum):
    CARD = "card"
    BANK = "bank"
    PAY = "pay"


class SourceKind(StrEnum):
    """Where the notification came from. Used to rank duplicates."""

    CARD_SMS = "card_sms"
    CARD_APP = "card_app"
    BANK_APP = "bank_app"
    BANK_SMS = "bank_sms"
    PAY_APP = "pay_app"


# Higher wins when the same payment is reported by several sources.
SOURCE_PRIORITY: dict[SourceKind, int] = {
    SourceKind.CARD_SMS: 50,
    SourceKind.CARD_APP: 40,
    SourceKind.BANK_APP: 45,
    SourceKind.BANK_SMS: 35,
    SourceKind.PAY_APP: 10,
}


@dataclass(slots=True)
class RawNotification:
    """One Android notification as reported by the HA companion app."""

    package: str
    title: str | None
    text: str | None
    post_time: datetime
    big_text: str | None = None
    sub_text: str | None = None
    noti_id: str | None = None
    entity_id: str | None = None

    @property
    def body(self) -> str:
        for value in (self.big_text, self.text):
            if value and value != "null":
                return value
        return ""

    @property
    def clean_title(self) -> str:
        if not self.title or self.title == "null":
            return ""
        return self.title

    @property
    def clean_sub_text(self) -> str:
        if not self.sub_text or self.sub_text == "null":
            return ""
        return self.sub_text


@dataclass(slots=True)
class ParsedTransaction:
    direction: Direction
    amount: Decimal
    occurred_at: datetime
    method: Method
    source_kind: SourceKind
    parser: str
    issuer: str
    currency: str = "KRW"
    merchant: str | None = None
    account_label: str | None = None
    is_cancel: bool = False
    installment: str | None = None
    balance: int | None = None
    cumulative: int | None = None
    time_known: bool = True

    @property
    def priority(self) -> int:
        return SOURCE_PRIORITY[self.source_kind]


@dataclass(slots=True)
class ParsedSchedule:
    issuer: str
    title: str
    parser: str
    amount: Decimal | None = None
    due_date: date | None = None


@dataclass(slots=True)
class ParseResult:
    status: Status
    parser: str | None = None
    transaction: ParsedTransaction | None = None
    schedule: ParsedSchedule | None = None
    reason: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def keep_raw(self) -> bool:
        """Whether the raw notification may be stored (never for personal SMS)."""
        return self.status is not Status.DROPPED
