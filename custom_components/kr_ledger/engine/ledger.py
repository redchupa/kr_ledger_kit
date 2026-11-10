"""Ledger rules: classify, categorise, and merge duplicate reports of one payment."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .models import Direction, Method, ParsedTransaction, SourceKind
from .normalize import within


class Kind(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"  # between the user's own accounts, card bill payments
    REFUND = "refund"  # card cancellation / refund (subtracts from expense)


# --------------------------------------------------------------------- owners

_PAREN_RE = re.compile(r"\(.*?\)")
_MASK = "*＊"


def _norm_name(name: str) -> str:
    return _PAREN_RE.sub("", name).replace("님", "").strip()


def _masked_equal(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    return all(x == y or x in _MASK or y in _MASK for x, y in zip(a, b, strict=True))


def is_owner(name: str | None, owners: Sequence[str]) -> bool:
    """True if ``name`` is one of the user's own names (masked forms allowed)."""
    if not name:
        return False
    n = _norm_name(name)
    if not n:
        return False
    if n.startswith("내 ") or n in ("내 통장", "내 계좌"):
        return True
    return any(_masked_equal(n, _norm_name(o)) for o in owners if o and o.strip())


# --------------------------------------------------------------------- categories

DEFAULT_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("세금", ("관세", "국세", "지방세", "세금", "과태료")),
    (
        "구독",
        (
            "넷플릭스",
            "NETFLIX",
            "유튜브",
            "YOUTUBE",
            "디즈니",
            "티빙",
            "웨이브",
            "왓챠",
            "멜론",
            "스포티파이",
            "SPOTIFY",
            "쿠팡와우",
            "APPLE.COM",
            "GOOGLE",
            "OPENAI",
            "ANTHROPIC",
            "CLAUDE",
        ),
    ),
    (
        "교통",
        (
            "택시",
            "카카오T",
            "KTX",
            "코레일",
            "SRT",
            "티머니",
            "하이패스",
            "주차",
            "주유",
            "오일",
            "에너지",
            "칼텍스",
            "S-OIL",
            "고속도로",
            "버스",
            "지하철",
        ),
    ),
    ("통신", ("LG U+", "LGU+", "통신요금", "SK텔레콤", "SKT", "KT", "알뜰폰")),
    (
        "식비",
        (
            "우아한형제들",
            "우아한",
            "배달의민족",
            "배민",
            "쿠팡이츠",
            "요기요",
            "커피",
            "카페",
            "스타벅스",
            "메가엠지씨",
            "매머드",
            "이디야",
            "투썸",
            "빽다방",
            "맥도날드",
            "버거",
            "치킨",
            "피자",
            "식당",
            "국수",
            "분식",
            "김밥",
            "베이커리",
            "파리바게뜨",
            "뚜레쥬르",
            "하이디라오",
            "푸드",
            "레스토랑",
            "막국수",
        ),
    ),
    (
        "마트·생활",
        (
            "마트",
            "이마트",
            "홈플러스",
            "코스트코",
            "편의점",
            "GS25",
            "CU",
            "세븐일레븐",
            "다이소",
            "액션",
            "ACTION",
            "식품",
            "청과",
            "정육",
            "슈퍼",
        ),
    ),
    ("의료", ("병원", "의원", "약국", "치과", "한의원", "의료", "클리닉")),
    ("주거·공과금", ("관리비", "전기", "도시가스", "수도", "한전", "아파트")),
    ("교육", ("학원", "교육", "서점", "교보문고", "YES24", "알라딘")),
    ("문화·여가", ("CGV", "메가박스", "롯데시네마", "영화", "공연", "티켓", "여행", "호텔", "숙박")),
    (
        "쇼핑",
        (
            "쿠팡",
            "네이버",
            "11번가",
            "지마켓",
            "G마켓",
            "옥션",
            "ALIEXPR",
            "ALIEXPRESS",
            "알리",
            "테무",
            "TEMU",
            "무신사",
            "SSG",
            "토스페이먼츠",
            "KG이니시스",
            "카카오페이",
            "페이코",
        ),
    ),
)

_ASCII_RE = re.compile(r"^[A-Za-z0-9 .+\-]+$")


def _kw_match(keyword: str, text: str) -> bool:
    if _ASCII_RE.match(keyword):
        return re.search(rf"(?<![A-Za-z]){re.escape(keyword)}(?![A-Za-z])", text, re.IGNORECASE) is not None
    return keyword in text


def categorize(
    merchant: str | None,
    rules: Iterable[tuple[str, Iterable[str]]] | None = None,
) -> str | None:
    if not merchant:
        return None
    for category, keywords in rules if rules is not None else DEFAULT_CATEGORIES:
        if any(_kw_match(k, merchant) for k in keywords):
            return category
    return None


# --------------------------------------------------------------------- classify

_CARD_BILL_RE = re.compile(r"(롯데|현대|KB|국민|하나|신한|삼성|BC|비씨|NH|농협|우리)\s*카드")


@dataclass(slots=True)
class Classification:
    kind: Kind
    category: str | None


def classify(
    tx: ParsedTransaction,
    owners: Sequence[str] = (),
    rules: Iterable[tuple[str, Iterable[str]]] | None = None,
) -> Classification:
    if tx.is_cancel:
        return Classification(Kind.REFUND, categorize(tx.merchant, rules))
    if tx.method is Method.BANK:
        if is_owner(tx.merchant, owners):
            return Classification(Kind.TRANSFER, "이체")
        if tx.merchant and _CARD_BILL_RE.search(tx.merchant):
            return Classification(Kind.TRANSFER, "카드대금")
        if tx.direction is Direction.IN:
            return Classification(Kind.INCOME, "수입")
    if tx.direction is Direction.IN:
        return Classification(Kind.INCOME, "수입")
    return Classification(Kind.EXPENSE, categorize(tx.merchant, rules))


# --------------------------------------------------------------------- dedupe

_CARD_GROUP = {SourceKind.CARD_SMS, SourceKind.CARD_APP, SourceKind.PAY_APP}
_BANK_GROUP = {SourceKind.BANK_APP, SourceKind.BANK_SMS}


@dataclass(slots=True)
class Candidate:
    """A stored transaction as seen by the duplicate finder."""

    id: int
    amount: Decimal
    currency: str
    direction: Direction
    is_cancel: bool
    occurred_at: datetime
    time_known: bool
    source_kinds: set[SourceKind] = field(default_factory=set)
    cumulative: int | None = None
    issuer: str | None = None


def _group(kind: SourceKind) -> set[SourceKind]:
    return _CARD_GROUP if kind in _CARD_GROUP else _BANK_GROUP


def find_duplicate(tx: ParsedTransaction, candidates: Iterable[Candidate], window_minutes: float = 5) -> int | None:
    """Return the id of a stored transaction that ``tx`` is another report of.

    Rules:
    * same amount, currency, direction and cancel flag;
    * if both carry a card "누적" total from the same issuer, it decides;
    * otherwise times within ``window_minutes`` (same day if a time is unknown);
    * the sources must be different kinds in the same family (card SMS + card
      app + pay app, or bank app + bank SMS). Two card SMS with different text
      are two purchases.
    """
    best: tuple[float, int] | None = None
    for c in candidates:
        if c.amount != tx.amount or c.currency != tx.currency:
            continue
        if c.direction != tx.direction or c.is_cancel != tx.is_cancel:
            continue
        if tx.cumulative is not None and c.cumulative is not None and c.issuer == tx.issuer:
            if c.cumulative == tx.cumulative:
                return c.id
            continue
        if tx.source_kind in c.source_kinds:
            continue
        if not (c.source_kinds & _group(tx.source_kind)):
            continue
        if tx.time_known and c.time_known:
            if not within(tx.occurred_at, c.occurred_at, window_minutes):
                continue
        elif tx.occurred_at.date() != c.occurred_at.date():
            continue
        gap = abs((tx.occurred_at - c.occurred_at).total_seconds())
        if best is None or gap < best[0]:
            best = (gap, c.id)
    return best[1] if best else None


MERGE_FIELDS = ("merchant", "account_label", "issuer", "installment", "cumulative", "balance")


def merge_into(existing: dict, existing_priority: int, tx: ParsedTransaction) -> dict:
    """Fields to update on ``existing`` when ``tx`` is a duplicate report of it."""
    updates: dict = {}
    stronger = tx.priority > existing_priority
    for name in MERGE_FIELDS:
        new = getattr(tx, name)
        if new is None:
            continue
        if (stronger or existing.get(name) in (None, "")) and existing.get(name) != new:
            updates[name] = new
    if tx.time_known and (stronger or not existing.get("time_known")):
        updates["occurred_at"] = tx.occurred_at
        updates["time_known"] = True
    if stronger:
        updates["source_priority"] = tx.priority
        if existing.get("method") != tx.method.value:
            updates["method"] = tx.method.value
    return updates
