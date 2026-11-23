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
# "6,585원 입금" / "요금납부 19,100원 출금" (card bill paid from 토스뱅크)
_TOSS_TITLE_RE = re.compile(r"^(?:[가-힣A-Za-z]+\s+)?([\d,]+)\s*원\s*(입금|출금|자동이체|결제|송금|환불|결제 취소|결제취소)")
# title "이자납부완료" / body "마이너스대출의 이자 10,421원을 냈어요."
_TOSS_INTEREST_RE = re.compile(r"(\S+)의\s*이자\s*([\d,]+)\s*원을?\s*냈어요")
_TOSS_TITLE2_RE = re.compile(r"^(입금|출금|결제|송금)\s*([\d,]+)\s*원")
# title "요금납부 출금" / body "내 토스뱅크 통장에서 32,800원이 출금됐어요. 롯데카드자동이체"
_TOSS_SENTENCE_RE = re.compile(r"^(.+?)(?:에서|으로|로)\s*([\d,]+)\s*원이\s*(출금|입금)됐어요\.?\s*(.*)$")


def parse_toss(raw: RawNotification) -> ParsedTransaction | None:
    title = clean(raw.clean_title)
    if "실패" in title:
        return None  # "요금납부 132,810원 출금 실패": nothing moved
    body = clean(raw.body)
    # Newer Toss notifications carry no sub text; the account line still names the bank.
    sub = raw.clean_sub_text or ("토스뱅크" if "토스뱅크" in body else "토스")
    if im := _TOSS_INTEREST_RE.search(body):
        # loans live in 토스뱅크 even when the notification doesn't say so
        bank = raw.clean_sub_text or "토스뱅크"
        return ParsedTransaction(
            direction=Direction.OUT,
            amount=parse_decimal(im.group(2)),  # type: ignore[arg-type]
            occurred_at=raw.post_time,
            method=Method.BANK,
            source_kind=SourceKind.BANK_APP,
            parser="app.toss",
            issuer=bank,
            merchant=f"{im.group(1)} 이자",
            account_label=f"{bank} {im.group(1)}",
        )
    if (sm := _TOSS_SENTENCE_RE.match(body.splitlines()[0] if body else "")) and not _TOSS_TITLE_RE.match(title):
        out = sm.group(3) == "출금"
        # the memo can start with the billed phone number ("01012345678SKT"): keep the name only
        memo = re.sub(r"^\d{6,}", "", sm.group(4)).strip() or None
        bank = raw.clean_sub_text or ("토스뱅크" if "토스뱅크" in sm.group(1) else "토스")
        return ParsedTransaction(
            direction=Direction.OUT if out else Direction.IN,
            amount=parse_decimal(sm.group(2)),  # type: ignore[arg-type]
            occurred_at=raw.post_time,
            method=Method.BANK,
            source_kind=SourceKind.BANK_APP,
            parser="app.toss",
            issuer=bank,
            merchant=memo,
            account_label=f"{bank} {sm.group(1).strip()}",
        )
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
        counterparty = body.split("\n")[0] or None
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


# ---------------------------------------------------------------- 케이뱅크
_KBANK_FIRST_RE = re.compile(r"^(입금|출금)(취소)?\s*([\d,]+)\s*원$")


def parse_kbank(raw: RawNotification) -> ParsedTransaction | None:
    """title ``케이뱅크`` / body ``입금 3,000,000원 / 상대방 | 생활통장(0000) / 잔액 3,109,662원`` (one line each)"""
    ls = lines(raw.body)
    if not ls or not (m := _KBANK_FIRST_RE.match(ls[0])):
        return None
    direction = Direction.IN if m.group(1) == "입금" else Direction.OUT
    counterparty = account = None
    if len(ls) > 1:
        left, _, right = ls[1].partition("|")
        left = re.sub(r"\s*\(\s*(.*?)\s*\)", r"(\1)", left)  # "대출실행 ( 원금 )" -> "대출실행(원금)"
        counterparty = re.sub(r"\s+", " ", left).strip() or None
        account = right.strip() or None
    return ParsedTransaction(
        direction=direction,
        amount=parse_decimal(m.group(3)),  # type: ignore[arg-type]
        occurred_at=raw.post_time,
        method=Method.BANK,
        source_kind=SourceKind.BANK_APP,
        parser="app.kbank",
        issuer="케이뱅크",
        merchant=counterparty,
        account_label=f"케이뱅크 {account}" if account else "케이뱅크",
        is_cancel=bool(m.group(2)),
        balance=_balance(raw.body),
    )


# ---------------------------------------------------------------- 하나카드 앱
# "(결제) 4,500원" / "(결제취소) -160,000원"
_HANA_TITLE_RE = re.compile(r"^\((결제|승인|취소|승인취소|결제취소)\)\s*(?:(USD|EUR|JPY|CNY)\s*)?-?\s*([\d,]+(?:\.\d+)?)\s*원?$")
_HANA_WHEN_RE = re.compile(r"\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2}")
# the card field: "신용(일시불,0*0*)" / "체크(0*0*)" — not a merchant's "(주)"
_HANA_CARD_RE = re.compile(r"^[가-힣]{0,4}\(([^,)]+),?([\d*]+)?\)$")


def parse_hanacard_app(raw: RawNotification) -> ParsedTransaction | None:
    """title ``(결제) 4,500원`` / body ``가맹점 / 신용(일시불,0*0*) / 11.09 15:16 / 누적이용금액 ...``"""
    m = _HANA_TITLE_RE.match(clean(raw.clean_title))
    if not m:
        return None
    parts = [p.strip() for p in re.split(r"\s*/\s*|\n", clean(raw.body)) if p.strip()]
    # A cancellation lists the cancelled discount first and the merchant last:
    # "할인취소 -10,320원 / 신용(일시불,0*0*) / 11.20 13:38 / 가맹점"
    parts = [p for p in parts if not p.startswith(("할인취소", "할인 취소"))]
    merchant = next((p for p in parts if not _HANA_CARD_RE.match(p) and not _HANA_WHEN_RE.search(p) and "누적" not in p), None)
    installment = None
    label = "하나카드"
    for p in parts:
        if cm := _HANA_CARD_RE.match(p):
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
# "₩19,800 결제 완료" (Samsung Pay) / "19,800원 결제 완료" (Samsung Wallet variants)
_SPAY_TITLE_RE = re.compile(r"^(?:₩\s*([\d,]+)|([\d,]+)\s*원)\s*(결제\s*완료|결제\s*취소|환불)")


def parse_samsung_pay(raw: RawNotification) -> ParsedTransaction | None:
    """title ``₩19,800 결제 완료`` / body ``가맹점``"""
    m = _SPAY_TITLE_RE.match(clean(raw.clean_title))
    if not m:
        return None
    body = clean(raw.body)
    return ParsedTransaction(
        direction=Direction.OUT,
        amount=parse_decimal(m.group(1) or m.group(2)),  # type: ignore[arg-type]
        occurred_at=raw.post_time,
        method=Method.PAY,
        source_kind=SourceKind.PAY_APP,
        parser="app.samsung_pay",
        issuer="삼성페이",
        merchant=body.split("\n")[0] if body else None,
        account_label=None,
        is_cancel="취소" in m.group(3) or "환불" in m.group(3),
    )


APP_PARSERS: dict[str, AppParser] = {
    "com.kakaobank.channel": parse_kakaobank,
    "viva.republica.toss": parse_toss,
    "com.shinhan.sbanking": parse_shinhan_sol,
    "com.kbankwith.smartbank": parse_kbank,
    "com.hanaskcard.paycla": parse_hanacard_app,
    "com.hanaskcard.rocomo.potal": parse_hanacard_app,
    "com.samsung.android.spay": parse_samsung_pay,
}
