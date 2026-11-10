"""Turn companion-app sensor attributes into RawNotification objects.

Two sensors are supported:

* ``*_last_notification`` - one notification per state change. When an app
  posts a notification and then an (empty) group summary within the same
  second - Samsung Pay and Samsung Messages both do this - the sensor often
  ends up with only the summary, and the real content is lost.
* ``*_active_notification_count`` - every notification currently in the
  shade, flattened into attributes like ``android.title_<package>_<id>`` and
  ``<package>_<id>_post_time``. It still holds the content the first sensor
  missed, so reading both closes that gap.

SMS notifications (MessagingStyle) also carry ``android.messages``: every
message in the conversation with its own timestamp. Two card SMS from the same
sender in quick succession collapse into one notification, so each message is
expanded into its own RawNotification.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, tzinfo
from typing import Any

from .filters import is_chat
from .models import RawNotification

POST_TIME_SUFFIX = "_post_time"

_MESSAGE_RE = re.compile(
    r"sender=(?P<sender>.*?), (?:uri=[^,]*, )?text=(?P<text>.*), time=(?P<time>\d+)(?:, type=[^}]*)?\}\s*$",
    re.DOTALL,
)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return None if text == "null" else text


def _when(ms: Any, tz: tzinfo) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, UTC).astimezone(tz)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def parse_messages(value: Any) -> list[tuple[str, str, int]]:
    """Parse ``android.messages`` into ``(sender, text, time_ms)`` tuples."""
    if not isinstance(value, list | tuple):
        return []
    out = []
    for item in value:
        if m := _MESSAGE_RE.search(str(item)):
            out.append((m.group("sender"), m.group("text"), int(m.group("time"))))
    return out


def _expand(base: RawNotification, messages: Any, tz: tzinfo) -> list[RawNotification]:
    """One RawNotification per SMS in a conversation notification."""
    parsed = parse_messages(messages)
    if not is_chat(base.package) or not parsed:
        return [base]
    out = []
    for sender, text, time_ms in parsed:
        when = _when(time_ms, tz)
        if when is None:
            continue
        out.append(
            RawNotification(
                package=base.package,
                title=sender or base.title,
                text=text,
                post_time=when,
                entity_id=base.entity_id,
                noti_id=base.noti_id,
            )
        )
    return out or [base]


def is_active_notifications(attrs: Mapping[str, Any]) -> bool:
    return "package" not in attrs and any(k.endswith(POST_TIME_SUFFIX) for k in attrs)


def from_last_notification(attrs: Mapping[str, Any], entity_id: str | None, tz: tzinfo) -> list[RawNotification]:
    package = attrs.get("package")
    when = _when(attrs.get("post_time"), tz)
    if not package or when is None:
        return []
    base = RawNotification(
        package=str(package),
        title=_clean(attrs.get("android.title")),
        text=_clean(attrs.get("android.text")),
        big_text=_clean(attrs.get("android.bigText")),
        sub_text=_clean(attrs.get("android.subText")),
        noti_id=str(attrs.get("pde_noti_id") or ""),
        post_time=when,
        entity_id=entity_id,
    )
    return _expand(base, attrs.get("android.messages"), tz)


def active_keys(attrs: Mapping[str, Any]) -> dict[str, Any]:
    """``{"<package>_<id>": post_time_ms}`` for every active notification."""
    return {k[: -len(POST_TIME_SUFFIX)]: v for k, v in attrs.items() if k.endswith(POST_TIME_SUFFIX)}


def from_active_notifications(
    attrs: Mapping[str, Any],
    entity_id: str | None,
    tz: tzinfo,
    only_keys: set[str] | None = None,
) -> list[RawNotification]:
    out: list[RawNotification] = []
    for key, post_ms in active_keys(attrs).items():
        if only_keys is not None and key not in only_keys:
            continue
        when = _when(post_ms, tz)
        if when is None:
            continue
        package = key.rsplit("_", 1)[0] if "_" in key else key
        base = RawNotification(
            package=package,
            title=_clean(attrs.get(f"android.title_{key}")),
            text=_clean(attrs.get(f"android.text_{key}")),
            big_text=_clean(attrs.get(f"android.bigText_{key}")),
            sub_text=_clean(attrs.get(f"android.subText_{key}")),
            noti_id=key,
            post_time=when,
            entity_id=entity_id,
        )
        out.extend(_expand(base, attrs.get(f"android.messages_{key}"), tz))
    return out


def raws_from_attributes(
    attrs: Mapping[str, Any],
    entity_id: str | None,
    tz: tzinfo,
    previous: Mapping[str, Any] | None = None,
) -> list[RawNotification]:
    """Notifications in a state's attributes that are new compared to ``previous``."""
    if is_active_notifications(attrs):
        keys = None
        if previous is not None and is_active_notifications(previous):
            old = active_keys(previous)
            keys = {k for k, v in active_keys(attrs).items() if old.get(k) != v}
        return from_active_notifications(attrs, entity_id, tz, keys)
    if previous is not None and previous.get("post_time") == attrs.get("post_time"):
        return []
    return from_last_notification(attrs, entity_id, tz)
