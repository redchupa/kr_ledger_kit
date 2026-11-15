"""Bank deposit/withdrawal SMS (입금 / 출금).

[신한은행]11/09 / 16:41:08 / [110-***-000000] / 출금 / 1,000원 / (홍길동)
"""

from __future__ import annotations

import re

from .models import Direction, Method, ParsedTransaction, RawNotification, SourceKind
from .normalize import find_md_time, lines, parse_decimal, parse_int

_BANK_RE = re.compile(r"\[([^\]]*(?:은행|뱅크|금고|신협|우체국|KB|NH|IBK|SC제일))\]")
# "대출금" contains "출금": never read it as a withdrawal.
_DIR_RE = re.compile(r"(입금취소|출금취소|이체출금|전자금융출금|타행이체|입금|(?<!대)출금)")
_BANK_NAMES = {"KB": "KB국민은행", "NH": "NH농협은행", "IBK": "IBK기업은행", "SC제일": "SC제일은행"}
# KB국민은행 SMS put the amount on its own line without "원": 출금 / 160,370 / 잔액626,471
_BARE_AMOUNT_RE = re.compile(r"^(\d{1,3}(?:,\d{3})+|\d+)$")
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
    if "대출" in text and ("실행" in text or "안내" in text):
        return None  # loan notices: the money itself arrives as a separate deposit notification

    scan = _BALANCE_RE.sub("", text)
    amount = None
    if amount_m := _AMOUNT_RE.search(scan):
        amount = parse_decimal(amount_m.group(1))
    else:
        after_dir = False
        for line in ls:
            if _DIR_RE.fullmatch(line.strip()):
                after_dir = True
            elif after_dir and (bm := _BARE_AMOUNT_RE.match(line.strip())):
                amount = parse_decimal(bm.group(1))
                break
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
        skip = re.compile(r"^\[|입금|출금|잔액|\d{1,2}[/.]\d{1,2}|^\d{1,2}:\d{2}|원$|^[\d,*\-]+$")
        rest = [line for line in ls if not skip.search(line) and not _ACCOUNT_RE.fullmatch(line.strip())]
        if rest:
            counterparty = rest[0]

    balance = None
    if m := _BALANCE_RE.search(text):
        balance = parse_int(m.group(1))

    bank = _BANK_NAMES.get(bank_m.group(1), bank_m.group(1))
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
