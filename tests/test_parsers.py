"""Fixture-driven parser tests. Every fixture is synthetic / anonymised."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from engine import RawNotification, Status, classify, parse

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "notifications.json").read_text(encoding="utf-8"))
OWNERS = ["홍길동"]


def _raw(fx: dict) -> RawNotification:
    return RawNotification(
        package=fx["package"],
        title=fx.get("title"),
        text=fx.get("body"),
        big_text=fx.get("body"),
        sub_text=fx.get("sub_text"),
        post_time=datetime.fromisoformat(fx["post_time"]),
    )


@pytest.mark.parametrize("fx", FIXTURES, ids=[f["id"] for f in FIXTURES])
def test_fixture(fx: dict) -> None:
    result = parse(_raw(fx))
    expect = dict(fx["expect"])
    assert result.status == Status(expect.pop("status")), result.reason
    if "parser" in expect:
        assert result.parser == expect.pop("parser")

    if result.status is Status.TRANSACTION:
        tx = result.transaction
        assert tx is not None
        cls = classify(tx, OWNERS)
        for key, want in expect.items():
            if key == "kind":
                assert cls.kind == want
            elif key == "category":
                assert cls.category == want
            elif key == "occurred_at":
                assert tx.occurred_at.strftime("%Y-%m-%dT%H:%M") == want
            elif key == "amount":
                assert str(tx.amount) == want
            else:
                assert getattr(tx, key) == want, key
    elif result.status is Status.SCHEDULE:
        sched = result.schedule
        assert sched is not None
        for key, want in expect.items():
            got = getattr(sched, key)
            if key == "due_date":
                got = got.isoformat() if got else None
            elif key == "amount":
                got = str(got)
            assert got == want, key
    else:
        assert result.transaction is None


def test_personal_sms_never_kept() -> None:
    raw = RawNotification(
        package="com.samsung.android.messaging",
        title="010-1234-5678",
        text="오늘 입금 50,000원 했어요 확인 부탁해요",
        post_time=datetime.fromisoformat("2026-11-10T10:00:00+09:00"),
    )
    result = parse(raw)
    assert result.status is Status.DROPPED
    assert not result.keep_raw
