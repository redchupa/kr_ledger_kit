"""End-to-end: raw notifications -> SQLite ledger, including dedupe and transfers."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from engine import RawNotification, Status
from engine.processor import LedgerProcessor
from engine.store import LedgerStore


@pytest.fixture
def proc(tmp_path) -> LedgerProcessor:
    store = LedgerStore(tmp_path / "ledger.db")
    store.open()
    yield LedgerProcessor(store, owners=["홍길동"])
    store.close()


def _raw(package: str, title: str, body: str, at: str, sub: str | None = None) -> RawNotification:
    return RawNotification(package=package, title=title, text=body, big_text=body, sub_text=sub,
                           post_time=datetime.fromisoformat(at))  # fmt: skip


SMS = "com.samsung.android.messaging"


def test_one_payment_three_notifications(proc: LedgerProcessor) -> None:
    a = proc.process(
        _raw(
            "com.hanaskcard.paycla",
            "(결제) 19,800원",
            "과일가게 / 신용(일시불,1*2*) / 11.07 20:23 / 누적이용금액 1,141,938원",
            "2026-11-07T20:23:05+09:00",
        )
    )
    b = proc.process(_raw("com.samsung.android.spay", "₩19,800 결제 완료", "과일가게", "2026-11-07T20:23:20+09:00"))
    c = proc.process(
        _raw(
            SMS,
            "하나카드결재",
            "[Web발신]\n하나1*2*승인 홍*동 19,800원 일시불 11/07 20:23 과일가게 누적1,141,938원",
            "2026-11-07T20:23:40+09:00",
        )
    )
    assert a.new_transaction
    assert b.merged and b.transaction_id == a.transaction_id
    assert c.merged and c.transaction_id == a.transaction_id
    rows = proc.store.list_transactions(date(2026, 11, 1), date(2026, 11, 30))
    assert len(rows) == 1
    tx = rows[0]
    assert tx["amount"] == 19800
    assert set(tx["source_kinds"]) == {"card_app", "pay_app", "card_sms"}
    assert tx["account_label"] == "하나1*2*"
    assert tx["issuer"] == "하나카드"


def test_identical_repost_ignored(proc: LedgerProcessor) -> None:
    body = "[Web발신]\n현대 사업구매전용 승인\n홍*동\n100,000원 일시불\n11/05 23:24\n네이버파이\n누적1,586,315원"
    outs = [proc.process(_raw(SMS, "1577-6200", body, f"2026-11-05T23:24:{s:02d}+09:00")) for s in (10, 20, 30)]
    assert outs[0].new_transaction
    assert not outs[1].new_transaction and not outs[2].new_transaction
    assert len(proc.store.list_transactions(date(2026, 11, 5), date(2026, 11, 5))) == 1


def test_same_amount_two_purchases(proc: LedgerProcessor) -> None:
    for minute, cum in ((22, "1,122,138"), (23, "1,127,138")):
        proc.process(
            _raw(
                SMS,
                "하나카드결재",
                f"[Web발신]\n하나1*2*승인 홍*동 5,000원 일시불 11/07 20:{minute} 가게 누적{cum}원",
                f"2026-11-07T20:{minute}:30+09:00",
            )
        )
    assert len(proc.store.list_transactions(date(2026, 11, 7), date(2026, 11, 7))) == 2


def test_transfer_pair_between_own_accounts(proc: LedgerProcessor) -> None:
    out = proc.process(_raw("com.kakaobank.channel", "출금 500,000원", "생활비(1111) → 김가게\n잔액 0원", "2026-11-05T06:55:00+09:00"))
    assert out.transaction["kind"] == "expense"
    inn = proc.process(
        _raw("viva.republica.toss", "500,000원 입금", "김가게 → 내 토스뱅크 통장", "2026-11-05T06:56:00+09:00", sub="토스뱅크")
    )
    # "내 토스뱅크 통장" counterparty -> transfer, and the earlier withdrawal is re-labelled too
    assert inn.transaction["kind"] == "transfer"
    rows = proc.store.list_transactions(date(2026, 11, 5), date(2026, 11, 5))
    assert {r["kind"] for r in rows} == {"transfer"}


def test_personal_sms_not_stored(proc: LedgerProcessor) -> None:
    out = proc.process(_raw(SMS, "010-1111-2222", "입금 50,000원 했어요", "2026-11-05T06:55:00+09:00"))
    assert out.status is Status.DROPPED
    assert out.raw_id is None


def test_schedule_dedup(proc: LedgerProcessor) -> None:
    body = "[Web발신]\n[롯데카드]11/16출금예정2,668,841원"
    first = proc.process(_raw(SMS, "롯데카드", body, "2026-11-06T09:46:00+09:00"))
    second = proc.process(_raw(SMS, "롯데카드", body, "2026-11-08T09:46:00+09:00"))
    assert first.schedule_id is not None
    assert second.schedule_id is None
    assert len(proc.store.list_schedules(date(2026, 11, 1), date(2026, 11, 30))) == 1


def test_daily_totals_and_refund(proc: LedgerProcessor) -> None:
    proc.process(
        _raw(
            SMS, "롯데카드", "[Web발신]\n가게\n10,000원 승인\n홍*동 롯데1234\n일시불 11/06 10:00\n누적10,000원", "2026-11-06T10:00:10+09:00"
        )
    )
    proc.process(_raw(SMS, "롯데카드", "[Web발신]\n가게\n3,000원 취소완료\n홍*동 롯데1234\n11/06", "2026-11-06T18:00:00+09:00"))
    totals = proc.store.daily_totals(date(2026, 11, 1), date(2026, 11, 30))
    assert totals["2026-11-06"]["expense"] == 10000
    assert totals["2026-11-06"]["refund"] == 3000
    assert totals["2026-11-06"]["net_expense"] == 7000


def test_category_learning(proc: LedgerProcessor) -> None:
    body = "[Web발신]\n현대 MY BUSINESS 승인\n홍*동\n{amt}원 일시불\n11/09 {t}\n주식회사거래처\n누적{cum}원"
    first = proc.process(_raw(SMS, "1577-6200", body.format(amt="65,140", t="09:50", cum="100,000"), "2026-11-09T09:50:10+09:00"))
    second = proc.process(_raw(SMS, "1577-6200", body.format(amt="1,000", t="10:50", cum="101,000"), "2026-11-09T10:50:10+09:00"))
    assert first.transaction["category"] is None
    proc.edit(first.transaction_id, {"category": "사업비"})
    assert proc.store.get_transaction(second.transaction_id)["category"] == "사업비"
    third = proc.process(_raw(SMS, "1577-6200", body.format(amt="2,000", t="11:50", cum="103,000"), "2026-11-09T11:50:10+09:00"))
    assert third.transaction["category"] == "사업비"


def test_excluded_account_not_counted(proc: LedgerProcessor) -> None:
    proc.process(
        _raw(
            SMS,
            "롯데카드",
            "[Web발신]\n가게\n10,000원 승인\n홍*동 롯데법인1234\n일시불 11/06 10:00\n누적10,000원",
            "2026-11-06T10:00:10+09:00",
        )
    )
    acc = next(a for a in proc.store.list_accounts() if a["label"] == "롯데법인1234")
    proc.store.update_account(acc["id"], include=0, owner_type="business")
    assert proc.store.daily_totals(date(2026, 11, 1), date(2026, 11, 30)) == {}
