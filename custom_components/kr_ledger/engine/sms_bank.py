"""Bank deposit/withdrawal SMS (입금 / 출금).

[신한은행]11/09 / 16:41:08 / [110-***-000000] / 출금 / 1,000원 / (홍길동)
"""

from __future__ import annotations

import re

from .models import Direction, Method, ParsedTransaction, RawNotification, SourceKind
from .normalize import find_md_time, lines, parse_decimal, parse_int

_BANK_RE = re.compile(r"\[([^\]]*(?:은행|뱅크|금고|신협|우체국|KB|NH|IBK|SC제일))\]")
_DIR_RE = re.compile(r"(입금|출금|이체출금|전자금융출금|타행이체|입금취소|출금취소)")
_AMOUNT_RE = re.compile(r"(?<![\d,])(\d[\d,]*)\s*원")
_ACCOUNT_RE = re.compile(r"\[?(\d{2,6}-[\d*]{2,}-[\d*]{2,})\]?|\b(\d{3,}\*{2,}\d+)\b")
_BALANCE_RE = re.compile(r"잔액\s*:?\s*([\d,]+)\s*원?")


def parse_bank_sms(raw: RawNotification) -> ParsedTransaction | None:
    ls = lines(raw.body)
    text = "\n".join(ls)
    bank_m = _BANK_RE.search(text)
    dir_m = _DIR_RE.search(text)
    if not bank_m or not dir_m:
        return None
    if "승인" in text and "카드" in text:
        return None  # card message, not a bank one

    scan = _BALANCE_RE.sub("", text)
    amount_m = _AMOUNT_RE.search(scan)
    if not amount_m:
        return None
    amount = parse_decimal(amount_m.group(1))
    if amount is None:
        return None

    direction = Direction.IN if dir_m.group(1).startswith("입금") else Direction.OUT
    is_cancel = "취소" in dir_m.group(1)

    when = find_md_time(" ".join(ls), raw.post_time)
    occurred_at, time_known = when if when else (raw.post_time, False)

    account = None
    if m := _ACCOUNT_RE.search(text):
        account = m.group(1) or m.group(2)

    counterparty = None
    if m := re.search(r"^\(([^)]+)\)$", text, re.MULTILINE):
        counterparty = m.group(1).strip()
    else:
        skip = re.compile(r"^\[|입금|출금|잔액|\d{1,2}[/.]\d{1,2}|^\d{1,2}:\d{2}|원$")
        rest = [line for line in ls if not skip.search(line)]
        if rest:
            counterparty = rest[0]

    balance = None
    if m := _BALANCE_RE.search(text):
        balance = parse_int(m.group(1))

    bank = bank_m.group(1)
    return ParsedTransaction(
        direction=direction,
        amount=amount,
        occurred_at=occurred_at,
        time_known=time_known,
        method=Method.BANK,
        source_kind=SourceKind.BANK_SMS,
        parser="sms.bank",
        issuer=bank,
        merchant=counterparty,
        account_label=f"{bank} {account}" if account else bank,
        is_cancel=is_cancel,
        balance=balance,
    )
