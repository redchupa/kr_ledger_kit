"""Credit/check card approval SMS (승인 / 취소 / 해외승인 / 자동이체).

Korean card companies use a handful of layouts. Rather than one regex per
company, each line is given a role (card line, amount, date, name, cumulative)
and the merchant is whatever is left, which handles all of these:

    롯데:  가맹점 / 12,800원 승인 / 홍*동 롯데0000 / 일시불 11/10 09:27 / 누적...
    현대:  현대 MY BUSINESS 승인 / 홍*동 / 210,000원 일시불 / 11/10 10:26 / 가맹점 / 누적...
    KB:    KB국민카드0000승인 / 홍*동님 / 12,700원 일시불 / 11/07 18:32 / 가맹점 / 누적...
    하나:  하나0*0*승인 홍*동 4,500원 일시불 11/09 15:16 가맹점 누적1,146,438원   (한 줄)
    삼성:  삼성0000승인 홍*동 / 12,000원 일시불 / 11/10 12:34 가맹점 / 누적...
"""

from __future__ import annotations

import re
from decimal import Decimal

from .models import Direction, Method, ParsedTransaction, RawNotification, SourceKind
from .normalize import MD_TIME_RE, find_md_time, lines, parse_decimal, parse_int

# (keyword, canonical issuer). Longer keywords first.
CARD_ISSUERS: tuple[tuple[str, str], ...] = (
    ("KB국민", "KB국민카드"),
    ("국민", "KB국민카드"),
    ("롯데", "롯데카드"),
    ("현대", "현대카드"),
    ("하나", "하나카드"),
    ("신한", "신한카드"),
    ("삼성", "삼성카드"),
    ("비씨", "BC카드"),
    ("BC", "BC카드"),
    ("농협", "NH농협카드"),
    ("NH", "NH농협카드"),
    ("우리", "우리카드"),
    ("씨티", "씨티카드"),
    ("IBK", "IBK기업은행카드"),
    ("기업", "IBK기업은행카드"),
    ("카카오뱅크", "카카오뱅크카드"),
    ("토스뱅크", "토스뱅크카드"),
    ("케이뱅크", "케이뱅크카드"),
    ("수협", "수협카드"),
    ("우체국", "우체국카드"),
)

CURRENCIES = "USD|EUR|JPY|CNY|GBP|HKD|SGD|AUD|CAD|THB|VND|PHP|TWD|CHF|NZD|MYR|IDR"

_AMOUNT_RE = re.compile(rf"(?:(?P<cur>{CURRENCIES})\s*(?P<famt>\d[\d,]*(?:\.\d+)?))|(?P<amt>\d[\d,]*)\s*원")
_STATUS_RE = re.compile(r"승인|취소")
_CUMULATIVE_RE = re.compile(r"누적(?:이용금액)?\s*:?\s*([\d,]+)\s*원?")
_TRAILING_RE = re.compile(r"(누적|잔여한도|잔여|사용가능|한도)\S*\s*:?\s*[\d,]+\s*원?.*$")
_INSTALLMENT_RE = re.compile(r"일시불|할부\s*\d+\s*개월|\d+\s*개월")
_MASKED_NAME_RE = re.compile(r"^[가-힣A-Za-z][*＊][가-힣A-Za-z*＊]{0,3}\s*님?$")
_MASKED_TOKEN_RE = re.compile(r"^[가-힣A-Za-z][*＊][가-힣A-Za-z*＊]{0,3}님?$")
_DATE_ONLY_RE = re.compile(r"^(?:일시불|할부\s*\d+\s*개월|\d+\s*개월)?\s*\d{1,2}[/.]\d{1,2}(?:\s*\d{1,2}:\d{2}(?::\d{2})?)?$")
_CARD_DIGITS_RE = re.compile(r"[\d*]{3,}")


def _card_line_issuer(line: str) -> str | None:
    for kw, issuer in CARD_ISSUERS:
        if kw not in line:
            continue
        idx = line.index(kw)
        rest = line[idx + len(kw) : idx + len(kw) + 14]
        if _CARD_DIGITS_RE.search(rest) or "카드" in rest[:3] or _STATUS_RE.search(line):
            return issuer
    return None


def _card_label(line: str, issuer_kw_line: bool, single_line: bool) -> str:
    if single_line:
        for token in line.split():
            if any(kw in token for kw, _ in CARD_ISSUERS):
                return re.sub(r"(해외)?승인|취소.*$", "", token).strip()
        return line
    tokens = [t for t in line.split() if not _MASKED_TOKEN_RE.match(t)]
    label = " ".join(tokens)
    label = re.sub(r"\s*(해외)?(승인|취소)\S*$", "", label).strip()
    return label


def parse_card_sms(raw: RawNotification) -> ParsedTransaction | None:
    ls = lines(raw.body)
    if not ls:
        return None
    joined = "\n".join(ls)
    if not _STATUS_RE.search(joined):
        return None

    card_idx = None
    issuer = None
    for i, line in enumerate(ls):
        if found := _card_line_issuer(line):
            card_idx, issuer = i, found
            break
    if issuer is None or card_idx is None:
        return None

    # amount: first money expression that isn't a cumulative/limit figure
    amount: Decimal | None = None
    currency = "KRW"
    amount_idx = None
    for i, line in enumerate(ls):
        scan = _TRAILING_RE.sub("", line)
        if m := _AMOUNT_RE.search(scan):
            if m.group("cur"):
                currency = m.group("cur")
                amount = parse_decimal(m.group("famt"))
            else:
                amount = parse_decimal(m.group("amt"))
            amount_idx = i
            break
    if amount is None or amount_idx is None:
        return None

    single_line = amount_idx == card_idx and MD_TIME_RE.search(ls[card_idx]) is not None

    when = find_md_time(_TRAILING_RE.sub("", joined), raw.post_time)
    occurred_at, time_known = when if when else (raw.post_time, False)

    cumulative = None
    if m := _CUMULATIVE_RE.search(joined):
        cumulative = parse_int(m.group(1))

    installment = None
    if m := _INSTALLMENT_RE.search(joined):
        installment = re.sub(r"\s+", "", m.group(0))

    merchant = _merchant(ls, card_idx, amount_idx, single_line)

    is_cancel = "취소" in joined
    return ParsedTransaction(
        direction=Direction.OUT,
        amount=amount,
        currency=currency,
        occurred_at=occurred_at,
        time_known=time_known,
        method=Method.CARD,
        source_kind=SourceKind.CARD_SMS,
        parser="sms.card",
        issuer=issuer,
        merchant=merchant,
        account_label=_card_label(ls[card_idx], True, single_line),
        is_cancel=is_cancel,
        installment=installment,
        cumulative=cumulative,
    )


def _merchant(ls: list[str], card_idx: int, amount_idx: int, single_line: bool) -> str | None:
    if single_line:
        line = ls[card_idx]
        m = MD_TIME_RE.search(line)
        if m is None:
            return None
        rest = _TRAILING_RE.sub("", line[m.end() :]).strip()
        return rest or None

    date_idx = None
    candidates: list[tuple[int, str]] = []
    for i, line in enumerate(ls):
        if i in (card_idx, amount_idx):
            # date + merchant on the same line as the amount (rare)
            continue
        stripped = _TRAILING_RE.sub("", line).strip()
        if not stripped:
            continue
        if _DATE_ONLY_RE.match(stripped):
            date_idx = i
            continue
        if MD_TIME_RE.match(stripped) or re.match(r"^(일시불|할부)", stripped):
            # "11/10 12:34 가맹점" (삼성) -> trailing text is the merchant
            date_idx = i
            m = next(MD_TIME_RE.finditer(stripped))
            rest = stripped[m.end() :].strip()
            if rest:
                return rest
            continue
        if _MASKED_NAME_RE.match(stripped) or stripped.startswith("["):
            continue
        candidates.append((i, stripped))

    if not candidates:
        return None
    if date_idx is not None:
        after = [c for i, c in candidates if i > date_idx]
        if after:
            return after[0]
    return candidates[0][1]
