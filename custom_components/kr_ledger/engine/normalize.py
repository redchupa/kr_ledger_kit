"""Text normalisation helpers shared by all parsers."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

# Bidi isolates / marks that Samsung Messages wraps around sender names and subjects.
_INVISIBLE = dict.fromkeys(map(ord, "⁨⁩‎‏‪‫‬‭‮﻿"))

SMS_TAGS = ("[Web발신]", "[국외발신]", "[국제발신]")

_SUBJECT_RE = re.compile(r"^<제목:.*?>\s*")


def clean(text: str | None) -> str:
    """Remove invisible characters and normalise newlines."""
    if not text or text == "null":
        return ""
    text = text.translate(_INVISIBLE).replace("\r\n", "\n").replace("\r", "\n")
    return text.replace(" ", " ").strip()


def lines(text: str | None) -> list[str]:
    """Clean text split into non-empty, stripped lines without SMS tags/subjects."""
    out: list[str] = []
    for raw in clean(text).split("\n"):
        line = _SUBJECT_RE.sub("", raw.strip()).strip()
        for tag in SMS_TAGS:
            if line.startswith(tag):
                line = line[len(tag) :].strip()
        if line:
            out.append(line)
    return out


def parse_int(value: str) -> int:
    return int(value.replace(",", "").strip())


def parse_decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", "").strip())
    except InvalidOperation:
        return None


def infer_date(month: int, day: int, ref: datetime) -> date | None:
    """Pick the year for a month/day found in a message posted at ``ref``.

    Messages never describe transactions far in the future, so if the date
    would land more than 31 days after the post time it belongs to last year
    (e.g. a 12/31 approval delivered on 01/01).
    """
    for year in (ref.year, ref.year - 1, ref.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        delta = (candidate - ref.date()).days
        if -335 <= delta <= 31:
            return candidate
    return None


def infer_future_date(month: int, day: int, ref: datetime) -> date | None:
    """Like :func:`infer_date` but for due dates, which are usually ahead."""
    for year in (ref.year, ref.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if (candidate - ref.date()).days >= -31:
            return candidate
    return None


def combine(d: date, hour: int | None, minute: int | None, ref: datetime) -> tuple[datetime, bool]:
    """Build an aware datetime in ``ref``'s timezone.

    Returns ``(datetime, time_known)``. When the message has no time we use the
    post time if it is the same day, otherwise noon.
    """
    tz = ref.tzinfo
    if hour is not None and minute is not None:
        return datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz), True
    if d == ref.date():
        return ref.replace(second=0, microsecond=0), False
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=tz), False


MD_TIME_RE = re.compile(r"(?<!\d)(\d{1,2})[/.](\d{1,2})(?:\s*(\d{1,2}):(\d{2})(?::\d{2})?)?(?!\d)")


def find_md_time(text: str, ref: datetime) -> tuple[datetime, bool] | None:
    """Find the first ``MM/DD[ HH:MM]`` or ``MM.DD[ HH:MM]`` in ``text``."""
    for m in MD_TIME_RE.finditer(text):
        month, day = int(m.group(1)), int(m.group(2))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        d = infer_date(month, day, ref)
        if d is None:
            continue
        hour = int(m.group(3)) if m.group(3) else None
        minute = int(m.group(4)) if m.group(4) else None
        if hour is not None and not (0 <= hour <= 23 and 0 <= (minute or 0) <= 59):
            hour = minute = None
        return combine(d, hour, minute, ref)
    return None


def within(a: datetime, b: datetime, minutes: float) -> bool:
    return abs(a - b) <= timedelta(minutes=minutes)
