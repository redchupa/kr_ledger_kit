from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from engine import Direction, Method, ParsedTransaction, SourceKind, categorize, find_duplicate, is_owner, merge_into
from engine.ledger import Candidate


def _tx(amount: str, at: str, kind: SourceKind, **kw) -> ParsedTransaction:
    return ParsedTransaction(
        direction=kw.pop("direction", Direction.OUT),
        amount=Decimal(amount),
        occurred_at=datetime.fromisoformat(at),
        method=kw.pop("method", Method.CARD),
        source_kind=kind,
        parser="test",
        issuer=kw.pop("issuer", "하나카드"),
        **kw,
    )


def _cand(id_: int, tx: ParsedTransaction) -> Candidate:
    return Candidate(
        id=id_,
        amount=tx.amount,
        currency=tx.currency,
        direction=tx.direction,
        is_cancel=tx.is_cancel,
        occurred_at=tx.occurred_at,
        time_known=tx.time_known,
        source_kinds={tx.source_kind},
        cumulative=tx.cumulative,
        issuer=tx.issuer,
    )


def test_sms_app_and_pay_merge() -> None:
    sms = _tx("19800", "2026-11-07T20:23:00+09:00", SourceKind.CARD_SMS, merchant="가게")
    app = _tx("19800", "2026-11-07T20:23:40+09:00", SourceKind.CARD_APP)
    pay = _tx("19800", "2026-11-07T20:24:10+09:00", SourceKind.PAY_APP, issuer="삼성페이")
    c = _cand(1, sms)
    assert find_duplicate(app, [c]) == 1
    c.source_kinds.add(SourceKind.CARD_APP)
    assert find_duplicate(pay, [c]) == 1


def test_two_real_purchases_same_amount_stay_separate() -> None:
    a = _tx("4500", "2026-11-09T15:16:00+09:00", SourceKind.CARD_SMS, cumulative=1000)
    b = _tx("4500", "2026-11-09T15:17:00+09:00", SourceKind.CARD_SMS, cumulative=5500)
    assert find_duplicate(b, [_cand(1, a)]) is None


def test_identical_cumulative_is_same_payment() -> None:
    a = _tx("100000", "2026-11-05T23:24:00+09:00", SourceKind.CARD_SMS, cumulative=1586315, issuer="현대카드")
    b = _tx("100000", "2026-11-05T23:24:00+09:00", SourceKind.CARD_SMS, cumulative=1586315, issuer="현대카드")
    assert find_duplicate(b, [_cand(7, a)]) == 7


def test_window_respected() -> None:
    a = _tx("1000", "2026-11-09T16:41:00+09:00", SourceKind.BANK_SMS, method=Method.BANK)
    b = _tx("1000", "2026-11-09T16:52:00+09:00", SourceKind.BANK_APP, method=Method.BANK)
    assert find_duplicate(b, [_cand(1, a)]) is None
    b2 = _tx("1000", "2026-11-09T16:42:00+09:00", SourceKind.BANK_APP, method=Method.BANK)
    assert find_duplicate(b2, [_cand(1, a)]) == 1


def test_bank_and_card_never_merge() -> None:
    a = _tx("1000", "2026-11-09T16:41:00+09:00", SourceKind.BANK_APP, method=Method.BANK)
    b = _tx("1000", "2026-11-09T16:41:00+09:00", SourceKind.CARD_SMS)
    assert find_duplicate(b, [_cand(1, a)]) is None


def test_merge_prefers_stronger_source() -> None:
    pay = _tx("19800", "2026-11-07T20:23:20+09:00", SourceKind.PAY_APP, issuer="삼성페이", merchant="가게")
    sms = _tx("19800", "2026-11-07T20:23:00+09:00", SourceKind.CARD_SMS, merchant="가게(본점)", account_label="하나1*2*")
    existing = {"merchant": "가게", "account_label": None, "issuer": "삼성페이", "time_known": True}
    updates = merge_into(existing, pay.priority, sms)
    assert updates["merchant"] == "가게(본점)"
    assert updates["account_label"] == "하나1*2*"
    assert updates["issuer"] == "하나카드"


def test_merge_upgrades_pay_to_card_method() -> None:
    pay = _tx("19800", "2026-11-07T20:23:20+09:00", SourceKind.PAY_APP, issuer="삼성페이", method=Method.PAY)
    app = _tx("19800", "2026-11-07T20:23:30+09:00", SourceKind.CARD_APP)
    updates = merge_into({"method": "pay", "time_known": True}, pay.priority, app)
    assert updates["method"] == "card"


def test_owner_matching() -> None:
    owners = ["홍길동"]
    assert is_owner("홍길동", owners)
    assert is_owner("홍*동", owners)
    assert is_owner("홍길동(가게)", owners)
    assert is_owner("홍*동님", owners)
    assert is_owner("내 토스뱅크 통장", owners)
    assert not is_owner("김철수", owners)
    assert not is_owner("홍길", owners)
    assert not is_owner(None, owners)


def test_categories() -> None:
    assert categorize("메가엠지씨커피") == "식비"
    assert categorize("관세(네이버페이)") == "세금"
    assert categorize("KTX 승차권") == "교통"
    assert categorize("넷플릭스서비시스") == "구독"
    assert categorize("알수없는가게") is None
    assert categorize("KTB투자") is None
