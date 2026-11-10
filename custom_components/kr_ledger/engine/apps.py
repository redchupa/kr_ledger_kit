"""Push notifications from bank / card / pay apps."""

from __future__ import annotations

import re
from collections.abc import Callable

from .models import Direction, Method, ParsedTransaction, RawNotification, SourceKind
from .normalize import clean, find_md_time, lines, parse_decimal, parse_int

AppParser = Callable[[RawNotification], ParsedTransaction | None]

_ARROW_RE = re.compile(r"^(.+?)\s*(?:→|->|➝)\s*(.+?)$")
_BALANCE_RE = re.compile(r"잔액\s*:?\s*([\d,]+)\s*원")


def _arrow(body: str) -> tuple[str, str] | None:
    for line in lines(body):
        if m := _ARROW_RE.match(line):
            return m.group(1).strip(), m.group(2).strip()
    return None


def _balance(body: str) -> int | None:
    if m := _BALANCE_RE.search(clean(body)):
        return parse_int(m.group(1))
    return None


# ---------------------------------------------------------------- 카카오뱅크
_KAKAO_TITLE_RE = re.compile(r"^(입금|출금)(취소)?\s*([\d,]+)\s*원$")


def parse_kakaobank(raw: RawNotification) -> ParsedTransaction | None:
    """title: ``출금 200,000원`` / body: ``내통장(0000) → 상대방\\n잔액 136,088원``"""
    m = _KAKAO_TITLE_RE.match(clean(raw.clean_title))
    if not m:
        return None
    direction = Direction.IN if m.group(1) == "입금" else Direction.OUT
    arrow = _arrow(raw.body)
    account = counterparty = None
    if arrow:
        src, dst = arrow
        account, counterparty = (dst, src) if direction is Direction.IN else (src, dst)
    return ParsedTransaction(
        direction=direction,
        amount=parse_decimal(m.group(3)),  # type: ignore[arg-type]
        occurred_at=raw.post_time,
        method=Method.BANK,
        source_kind=SourceKind.BANK_APP,
        parser="app.kakaobank",
        issuer="카카오뱅크",
        merchant=counterparty,
        account_label=f"카카오뱅크 {account}" if account else "카카오뱅크",
        is_cancel=bool(m.group(2)),
        balance=_balance(raw.body),
    )


# ---------------------------------------------------------------- 토스 / 토스뱅크
_TOSS_TITLE_RE = re.compile(r"^([\d,]+)\s*원\s*(입금|출금|결제|송금|환불|결제 취소|결제취소)")
_TOSS_TITLE2_RE = re.compile(r"^(입금|출금|결제|송금)\s*([\d,]+)\s*원")


def parse_toss(raw: RawNotification) -> ParsedTransaction | None:
    title = clean(raw.clean_title)
    if m := _TOSS_TITLE_RE.match(title):
        amount, kind = m.group(1), m.group(2)
    elif m := _TOSS_TITLE2_RE.match(title):
        kind, amount = m.group(1), m.group(2)
    else:
        return None
    # cancellations / refunds are modelled as a negative card-style expense
    direction = Direction.IN if kind == "입금" else Direction.OUT
    is_cancel = "취소" in kind or kind == "환불"
    arrow = _arrow(raw.body)
    account = counterparty = None
    if arrow:
        src, dst = arrow
        account, counterparty = (dst, src) if direction is Direction.IN else (src, dst)
    elif kind.startswith("결제"):
        counterparty = clean(raw.body).split("\n")[0] or None
    sub = raw.clean_sub_text or "토스"
    method = Method.PAY if kind.startswith("결제") else Method.BANK
    return ParsedTransaction(
        direction=direction,
        amount=parse_decimal(amount),  # type: ignore[arg-type]
        occurred_at=raw.post_time,
        method=method,
        source_kind=SourceKind.BANK_APP if method is Method.BANK else SourceKind.PAY_APP,
        parser="app.toss",
        issuer=sub,
        merchant=counterparty,
        account_label=f"{sub} {account}" if account else sub,
        is_cancel=is_cancel,
        balance=_balance(raw.body),
    )


# ---------------------------------------------------------------- 신한 SOL
_SHINHAN_BODY_RE = re.compile(r"^([\d,]+)\s*원\s*(.*?)\s*(\S+\(\d{3,4}\))\s*$")


def parse_shinhan_sol(raw: RawNotification) -> ParsedTransaction | None:
    """title ``출금`` / body ``1,000원 홍길동 입출금(0000)\\n11.09 16:41``"""
    title = clean(raw.clean_title)
    if title not in ("입금", "출금", "입금취소", "출금취소"):
        return None
    ls = lines(raw.body)
    if not ls or not (m := _SHINHAN_BODY_RE.match(ls[0])):
        return None
    when = find_md_time(" ".join(ls[1:]), raw.post_time)
    occurred_at, time_known = when if when else (raw.post_time, False)
    return ParsedTransaction(
        direction=Direction.IN if title.startswith("입금") else Direction.OUT,
        amount=parse_decimal(m.group(1)),  # type: ignore[arg-type]
        occurred_at=occurred_at,
        time_known=time_known,
        method=Method.BANK,
        source_kind=SourceKind.BANK_APP,
        parser="app.shinhan_sol",
        issuer="신한은행",
        merchant=m.group(2) or None,
        account_label=f"신한은행 {m.group(3)}",
        is_cancel="취소" in title,
        balance=_balance(raw.body),
    )


# ---------------------------------------------------------------- 하나카드 앱
_HANA_TITLE_RE = re.compile(r"^\((결제|승인|취소|승인취소|결제취소)\)\s*(?:(USD|EUR|JPY|CNY)\s*)?([\d,]+(?:\.\d+)?)\s*원?$")
_HANA_CARD_RE = re.compile(r"\(([^,)]+),?([\d*]+)?\)")


def parse_hanacard_app(raw: RawNotification) -> ParsedTransaction | None:
    """title ``(결제) 4,500원`` / body ``가맹점 / 신용(일시불,0*0*) / 11.09 15:16 / 누적이용금액 ...``"""
    m = _HANA_TITLE_RE.match(clean(raw.clean_title))
    if not m:
        return None
    parts = [p.strip() for p in re.split(r"\s*/\s*|\n", clean(raw.body)) if p.strip()]
    merchant = parts[0] if parts else None
    installment = None
    label = "하나카드"
    for p in parts[1:]:
        if cm := _HANA_CARD_RE.search(p):
            installment = cm.group(1)
            if cm.group(2):
                label = f"하나{cm.group(2)}"
            break
    when = find_md_time(" ".join(parts[1:]), raw.post_time)
    occurred_at, time_known = when if when else (raw.post_time, False)
    cumulative = None
    if cm := re.search(r"누적\S*\s*([\d,]+)\s*원", raw.body or ""):
        cumulative = parse_int(cm.group(1))
    return ParsedTransaction(
        direction=Direction.OUT,
        amount=parse_decimal(m.group(3)),  # type: ignore[arg-type]
        currency=m.group(2) or "KRW",
        occurred_at=occurred_at,
        time_known=time_known,
        method=Method.CARD,
        source_kind=SourceKind.CARD_APP,
        parser="app.hanacard",
        issuer="하나카드",
        merchant=merchant,
        account_label=label,
        is_cancel="취소" in m.group(1),
        installment=installment,
        cumulative=cumulative,
    )


# ---------------------------------------------------------------- 삼성페이
_SPAY_TITLE_RE = re.compile(r"^₩\s*([\d,]+)\s*(결제\s*완료|결제\s*취소|환불)")


def parse_samsung_pay(raw: RawNotification) -> ParsedTransaction | None:
    """title ``₩19,800 결제 완료`` / body ``가맹점``"""
    m = _SPAY_TITLE_RE.match(clean(raw.clean_title))
    if not m:
        return None
    body = clean(raw.body)
    return ParsedTransaction(
        direction=Direction.OUT,
        amount=parse_decimal(m.group(1)),  # type: ignore[arg-type]
        occurred_at=raw.post_time,
        method=Method.PAY,
        source_kind=SourceKind.PAY_APP,
        parser="app.samsung_pay",
        issuer="삼성페이",
        merchant=body.split("\n")[0] if body else None,
        account_label=None,
        is_cancel="취소" in m.group(2) or "환불" in m.group(2),
    )


APP_PARSERS: dict[str, AppParser] = {
    "com.kakaobank.channel": parse_kakaobank,
    "viva.republica.toss": parse_toss,
    "com.shinhan.sbanking": parse_shinhan_sol,
    "com.hanaskcard.paycla": parse_hanacard_app,
    "com.hanaskcard.rocomo.potal": parse_hanacard_app,
    "com.samsung.android.spay": parse_samsung_pay,
}
