"""Bills and upcoming payments (결제예정, 출금예정, 대출 납입 예정 ...)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .models import ParsedSchedule, RawNotification
from .normalize import clean, infer_future_date, parse_decimal

KEYWORDS_RE = re.compile(
    r"결제금액|출금예정|카드대금|결제예정|납입예정|납입 예정|납입일|청구금액|이용대금|나가는 날"
    r"|납부하실\s*금액|납부\s*금액|인출\s*예정|납부\s*기한|요금\s*안내"
)

_ISSUER_RE = re.compile(r"\[([^\]]*(?:카드|은행|뱅크))\]")

# [롯데카드]11/16출금예정2,668,841원 / [현대카드] 홍*동님 11/12결제금액 1,009,601원
# [KB국민카드]홍*동님 11/16 카드대금 1,540,916원
_MD_AMOUNT_RE = re.compile(r"(\d{1,2})/(\d{1,2})\s*(?:출금예정|결제금액|카드대금|결제예정금액|청구금액)\s*:?\s*([\d,]+)\s*원")
# 하나카드 앱: 11월 13일 결제예정금액은 319,938원
_KO_MD_AMOUNT_RE = re.compile(r"(\d{1,2})월\s*(\d{1,2})일\s*(?:결제예정금액|결제금액|출금예정금액)\S*\s*([\d,]+)\s*원")
# 현대카드 알림톡: "12일은 현대카드 이용 금액 결제일입니다 ... - 결제금액 : 1,161,511원 (10일 기준)"
_DAY_DUE_RE = re.compile(r"(?<!\d)(\d{1,2})일은[^\n]*결제일")
_LABELED_AMOUNT_RE = re.compile(r"(?:결제금액|결제예정금액|청구금액)\s*[:：]\s*([\d,]+)\s*원")
# 대출: 납입일은 2026.11.23 ... 납입예정금액 : 1,725,651원
_LOAN_DATE_RE = re.compile(r"납입일[은는]?\s*(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")
_LOAN_AMOUNT_RE = re.compile(r"납입예정금액\s*:?\s*([\d,]+)\s*원|원리금\s*([\d,]+)\s*원")
# 통신·공과금 요금안내: "납부하실 금액은 총 32,800원 ... 자동납부 : ○○은행 23일 인출 예정"
_BILL_AMOUNT_RE = re.compile(r"(?:납부하실|납부할|청구|납부)\s*금액[은는]?\s*[:：]?\s*(?:총\s*)?([\d,]+)\s*원")
_BILL_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})일\s*(?:에\s*)?(?:인출|출금|자동\s*납부|납부)\s*예정")
_BILL_DEADLINE_RE = re.compile(r"납부\s*기한\s*[:：]?\s*(?:(\d{4})\s*[.\-/년]\s*)?(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
_TELECOM_RE = re.compile(r"SKT|SK텔레콤|KT(?![A-Za-z])|LG\s?U\+|LG유플러스|알뜰폰|통신")
_BILLER_RE = re.compile(r"【\s*(SKT|KT|LG\s?U\+|[가-힣A-Za-z]+(?:공사|전력|가스|텔레콤))")
_TAX_RE = re.compile(r"지방세|국세|자동차세|재산세|주민세|세금")


def _next_day_of_month(day: int, today: date) -> date | None:
    """The next date (today included) whose day-of-month is ``day``."""
    year, month = today.year, today.month
    for _ in range(3):
        try:
            candidate = date(year, month, day)
        except ValueError:
            candidate = None
        if candidate and candidate >= today:
            return candidate
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return None


def parse_schedule(raw: RawNotification, issuer_hint: str) -> ParsedSchedule | None:
    title = clean(raw.clean_title)
    body = clean(raw.body)
    text = f"{title}\n{body}"
    if not KEYWORDS_RE.search(text):
        return None

    issuer = issuer_hint
    if m := _ISSUER_RE.search(text):
        issuer = m.group(1)

    if m := _MD_AMOUNT_RE.search(text) or _KO_MD_AMOUNT_RE.search(text):
        due = infer_future_date(int(m.group(1)), int(m.group(2)), raw.post_time)
        return ParsedSchedule(
            issuer=issuer,
            title="카드 결제 예정",
            parser="schedule.card_bill",
            amount=parse_decimal(m.group(3)),
            due_date=due,
        )

    if (dm := _DAY_DUE_RE.search(text)) and (am := _LABELED_AMOUNT_RE.search(text)):
        return ParsedSchedule(
            issuer=issuer,
            title="카드 결제 예정",
            parser="schedule.card_bill",
            amount=parse_decimal(am.group(1)),
            due_date=_next_day_of_month(int(dm.group(1)), raw.post_time.date()),
        )

    if m := _LOAN_DATE_RE.search(text):
        try:
            due: date | None = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            due = None
        amount = None
        if am := _LOAN_AMOUNT_RE.search(text):
            amount = parse_decimal(am.group(1) or am.group(2))
        loan = re.search(r"(\S*대출)\(?(\d{4})?\)?", text)
        name = loan.group(1) if loan else "대출"
        return ParsedSchedule(issuer=issuer, title=f"{name} 원리금 납입", parser="schedule.loan", amount=amount, due_date=due)

    if bill := _parse_bill(text, issuer, raw.post_time):
        return bill

    if "나가는 날" in text:
        # 토스: "내일은 넷플릭스 이용료 나가는 날이에요."
        m = re.search(r"(오늘|내일|모레)은?\s*(.+?)\s*나가는 날", body)
        what = m.group(2) if m else body
        due_r = None
        if m:
            due_r = raw.post_time.date() + timedelta(days={"오늘": 0, "내일": 1, "모레": 2}[m.group(1)])
        return ParsedSchedule(issuer=issuer, title=what, parser="schedule.reminder", due_date=due_r)

    return None


def _parse_bill(text: str, issuer: str, posted: datetime) -> ParsedSchedule | None:
    """Phone / utility / tax bills: an amount to pay plus a withdrawal day or a deadline."""
    am = _BILL_AMOUNT_RE.search(text)
    if not am:
        return None

    due: date | None = None
    if dm := _BILL_DAY_RE.search(text):
        due = _next_day_of_month(int(dm.group(1)), posted.date())
    elif dm := _BILL_DEADLINE_RE.search(text):
        year = int(dm.group(1)) if dm.group(1) else None
        try:
            if year:
                due = date(year, int(dm.group(2)), int(dm.group(3)))
            else:
                due = infer_future_date(int(dm.group(2)), int(dm.group(3)), posted)
        except (ValueError, TypeError):
            due = None
    if due is None:
        return None

    if m := _BILLER_RE.search(text):
        issuer = re.sub(r"\s+", "", m.group(1))
    if _TAX_RE.search(text):
        kind = "세금"
    elif _TELECOM_RE.search(text):
        kind = "통신요금"
    else:
        kind = "요금"
    auto = "자동납부" in re.sub(r"\s+", "", text) or "인출 예정" in text or "출금 예정" in text
    return ParsedSchedule(
        issuer=issuer,
        title=f"{kind} {'자동납부' if auto else '납부'}",
        parser="schedule.bill",
        amount=parse_decimal(am.group(1)),
        due_date=due,
    )
