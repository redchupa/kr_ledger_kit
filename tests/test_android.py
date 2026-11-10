"""Companion-app sensor attributes -> RawNotification (synthetic data)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from engine import Status, parse
from engine.android import from_active_notifications, parse_messages, raws_from_attributes
from engine.processor import LedgerProcessor
from engine.store import LedgerStore

KST = timezone(timedelta(hours=9))
T0 = int(datetime(2026, 11, 7, 20, 22, 30, tzinfo=KST).timestamp() * 1000)


def _msg(sender: str, text: str, ms: int, uri: bool = False) -> str:
    extra = ", uri=content://mms/part/1" if uri else ""
    return f"{{extras={{}}, sender_person=android.app.Person@1a2b, sender=⁨{sender}⁩{extra}, text={text}, time={ms}}}"


SMS_1 = "[Web발신]\n하나1*2*승인 홍*동 50,500원 일시불 11/07 20:22 과일가게 누적1,122,138원"
SMS_2 = "[Web발신]\n하나1*2*승인 홍*동 19,800원 일시불 11/07 20:23 과일가게 누적1,141,938원"


def test_parse_messages_handles_uri_and_multiline() -> None:
    items = [_msg("하나카드결재", SMS_1, T0, uri=True), _msg("하나카드결재", SMS_2, T0 + 60_000)]
    parsed = parse_messages(items)
    assert [p[2] for p in parsed] == [T0, T0 + 60_000]
    assert parsed[0][1] == SMS_1
    assert parsed[1][0] == "⁨하나카드결재⁩"


def test_last_notification_expands_conversation() -> None:
    attrs = {
        "package": "com.samsung.android.messaging",
        "post_time": T0 + 60_500,
        "android.title": "하나카드결재",
        "android.text": SMS_2,
        "android.messages": [_msg("하나카드결재", SMS_1, T0), _msg("하나카드결재", SMS_2, T0 + 60_000)],
    }
    raws = raws_from_attributes(attrs, "sensor.phone_last_notification", KST)
    assert [r.body for r in raws] == [SMS_1, SMS_2]
    assert [parse(r).transaction.amount for r in raws] == [50500, 19800]


def test_last_notification_same_post_time_is_skipped() -> None:
    attrs = {"package": "viva.republica.toss", "post_time": T0, "android.title": "x", "android.text": "y"}
    assert raws_from_attributes(attrs, None, KST, previous=dict(attrs)) == []
    assert len(raws_from_attributes(attrs, None, KST, previous=None)) == 1


ACTIVE = {
    # Samsung Pay child notification (the content the last-notification sensor lost)
    "android.title_com.samsung.android.spay_1002": "₩19,800 결제 완료",
    "android.text_com.samsung.android.spay_1002": "과일가게",
    "com.samsung.android.spay_1002_post_time": T0 + 61_000,
    # its empty group summary
    "android.title_com.samsung.android.spay_1001": "null",
    "android.text_com.samsung.android.spay_1001": "null",
    "com.samsung.android.spay_1001_post_time": T0 + 61_200,
    # a personal KakaoTalk chat - must be dropped
    "android.title_com.kakao.talk_2": "친구",
    "android.text_com.kakao.talk_2": "어제 5만원 입금했어",
    "com.kakao.talk_2_post_time": T0,
    "unit_of_measurement": "notifications",
    "friendly_name": "Phone Active notification count",
}


def test_active_notifications_recover_lost_content() -> None:
    raws = from_active_notifications(ACTIVE, "sensor.phone_active_notification_count", KST)
    by_pkg = {(r.package, r.noti_id): r for r in raws}
    spay = by_pkg[("com.samsung.android.spay", "com.samsung.android.spay_1002")]
    result = parse(spay)
    assert result.status is Status.TRANSACTION
    assert result.transaction.amount == 19800
    assert parse(by_pkg[("com.samsung.android.spay", "com.samsung.android.spay_1001")]).status is Status.DROPPED
    assert parse(by_pkg[("com.kakao.talk", "com.kakao.talk_2")]).status is Status.DROPPED


def test_active_notifications_only_new_keys() -> None:
    previous = {k: v for k, v in ACTIVE.items() if "spay_1002" not in k}
    raws = raws_from_attributes(ACTIVE, None, KST, previous=previous)
    assert [r.noti_id for r in raws] == ["com.samsung.android.spay_1002"]


def test_both_sensors_report_same_payment_once(tmp_path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.open()
    proc = LedgerProcessor(store)
    last = {
        "package": "com.samsung.android.spay",
        "post_time": T0 + 61_000,
        "android.title": "₩19,800 결제 완료",
        "android.text": "과일가게",
    }
    for raw in raws_from_attributes(last, "sensor.p_last_notification", KST):
        proc.process(raw)
    for raw in from_active_notifications(ACTIVE, "sensor.p_active_notification_count", KST):
        proc.process(raw)
    rows = store.list_transactions(date(2026, 11, 7), date(2026, 11, 7))
    assert len(rows) == 1 and rows[0]["amount"] == 19800
    store.close()
