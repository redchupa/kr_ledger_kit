"""Entry point: route one raw notification to the right parser."""

from __future__ import annotations

import re

from .apps import APP_PARSERS
from .filters import (
    FINANCIAL_PACKAGES,
    has_sms_tag,
    is_financial_package,
    is_financial_sender,
    is_kakao,
    is_messaging,
    is_otp,
    looks_like_money_movement,
)
from .models import ParseResult, RawNotification, Status
from .normalize import clean
from .schedule import parse_schedule
from .sms_bank import parse_bank_sms
from .sms_card import parse_card_sms

_NOISE_MARKERS = ("(광고)", "알림 끄기는", "쿠폰", "이벤트", "혜택")
# Notices about money that has not moved (or moved in another notification):
# "오늘 하나카드에서 319,938원 출금할 예정이에요", "요금납부 132,810원 출금 실패"
_NO_MOVEMENT_RE = re.compile(
    r"출금\s*실패|이체\s*실패|할\s*예정이에요|될\s*예정이에요|예정입니다|납부\s*예정|\d+\s*건의\s*\S*\s*자동이체가\s*있어요"
)
# Card companies confirming a bill payment or returning an overpayment. The money itself is
# recorded from the bank side ("내 통장 → 현대카드"), so these would only count it twice:
#   [현대카드] 홍*동님 11/13 1,629,213원이 입금되었습니다
#   [롯데카드] 홍*동 회원님, 11/17 토스뱅크에서 2,670,115원 출금되었습니다.
#   (하나카드 앱) 11월 13일 결제대금 319,938원이 출금되었습니다. / 345,278원이 선결제 되었습니다.
#   (KB Pay) 카드대금 165,001원 결제완료(오픈뱅킹) / (롯데카드 앱) 초과 납부한 금액을 환불받았어요
_CARD_BILL_NOTICE_RE = re.compile(
    r"원이?\s*입금되었습니다|원이?\s*출금되었습니다|선결제\s*되었습니다"
    r"|카드대금\s*[\d,]+\s*원\s*결제\s*완료|초과\s*납부|돌려받았어요|환불받았어요"
)


def _is_card_bill_notice(raw: RawNotification, text: str) -> bool:
    card_context = any(k in text for k in ("카드", "결제대금", "선결제")) or "카드" in FINANCIAL_PACKAGES.get(raw.package, "")
    return card_context and _CARD_BILL_NOTICE_RE.search(text) is not None


def parse(raw: RawNotification, extra_packages: frozenset[str] = frozenset()) -> ParseResult:
    title = clean(raw.clean_title)
    body = clean(raw.body)
    text = f"{title}\n{body}"

    if not title and not body:
        return ParseResult(Status.DROPPED, reason="empty (group summary)")
    if "민감한 알림 콘텐츠 숨김" in text:
        return ParseResult(Status.IGNORED, reason="redacted by Android")

    if is_messaging(raw.package):
        return _parse_sms(raw, text)
    if is_kakao(raw.package):
        return _parse_kakao(raw, text)

    if not is_financial_package(raw.package, extra_packages):
        return ParseResult(Status.DROPPED, reason="not a financial app")

    if is_otp(text):
        return ParseResult(Status.IGNORED, reason="authentication")

    issuer = FINANCIAL_PACKAGES.get(raw.package, raw.package)
    if sched := parse_schedule(raw, issuer):
        return ParseResult(Status.SCHEDULE, parser=sched.parser, schedule=sched)

    app_parser = APP_PARSERS.get(raw.package)
    if app_parser and (tx := app_parser(raw)):
        return ParseResult(Status.TRANSACTION, parser=tx.parser, transaction=tx)

    if _is_card_bill_notice(raw, text):
        return ParseResult(Status.IGNORED, reason="card bill payment notice (bank side recorded)")
    if any(marker in text for marker in _NOISE_MARKERS) or not looks_like_money_movement(text):
        return ParseResult(Status.IGNORED, reason="no money movement")
    if _NO_MOVEMENT_RE.search(text):
        return ParseResult(Status.IGNORED, reason="notice, no money moved")
    return ParseResult(Status.UNPARSED, reason="no rule matched")


def _try_message_parsers(raw: RawNotification, sender: str) -> ParseResult | None:
    if sched := parse_schedule(raw, sender):
        return ParseResult(Status.SCHEDULE, parser=sched.parser, schedule=sched)
    if tx := parse_card_sms(raw):
        return ParseResult(Status.TRANSACTION, parser=tx.parser, transaction=tx)
    if tx := parse_bank_sms(raw):
        return ParseResult(Status.TRANSACTION, parser=tx.parser, transaction=tx)
    return None


def _parse_sms(raw: RawNotification, text: str) -> ParseResult:
    if is_otp(text):
        return ParseResult(Status.DROPPED, reason="authentication SMS")
    sender = clean(raw.clean_title)

    if not has_sms_tag(raw.body):
        # Personal conversations never carry the carrier's [Web발신] tag. Some card
        # companies (RCS) omit it too, so a company sender still gets a strict parse,
        # but nothing from it is kept unless a rule matches.
        if is_financial_sender(sender) and (result := _try_message_parsers(raw, sender)):
            return result
        return ParseResult(Status.DROPPED, reason="personal SMS")

    if result := _try_message_parsers(raw, sender):
        return result
    if _is_card_bill_notice(raw, text):
        return ParseResult(Status.IGNORED, reason="card bill payment notice (bank side recorded)")
    if looks_like_money_movement(text) and not any(k in text for k in ("발송", "배송", "주문", "세금안내")):
        return ParseResult(Status.UNPARSED, reason="SMS with money but no rule matched")
    # Marketing / delivery / tax notices: not ours, don't keep the text.
    return ParseResult(Status.DROPPED, reason="non-financial SMS")


def _parse_kakao(raw: RawNotification, text: str) -> ParseResult:
    """KakaoTalk 알림톡 from card / bank channels. Personal chats are dropped."""
    sender = clean(raw.clean_title) or clean(raw.clean_sub_text)
    if not (is_financial_sender(sender) or is_financial_sender(clean(raw.clean_sub_text))):
        return ParseResult(Status.DROPPED, reason="personal chat")
    if is_otp(text):
        return ParseResult(Status.DROPPED, reason="authentication")
    if result := _try_message_parsers(raw, sender):
        return result
    if _is_card_bill_notice(raw, text):
        return ParseResult(Status.IGNORED, reason="card bill payment notice (bank side recorded)")
    if looks_like_money_movement(text) and not any(marker in text for marker in _NOISE_MARKERS):
        return ParseResult(Status.UNPARSED, reason="알림톡 with money but no rule matched")
    return ParseResult(Status.DROPPED, reason="non-financial 알림톡")
