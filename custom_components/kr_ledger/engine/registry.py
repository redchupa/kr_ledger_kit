"""Entry point: route one raw notification to the right parser."""

from __future__ import annotations

from .apps import APP_PARSERS
from .filters import (
    FINANCIAL_PACKAGES,
    has_sms_tag,
    is_financial_package,
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

    if any(marker in text for marker in _NOISE_MARKERS) or not looks_like_money_movement(text):
        return ParseResult(Status.IGNORED, reason="no money movement")
    return ParseResult(Status.UNPARSED, reason="no rule matched")


def _parse_sms(raw: RawNotification, text: str) -> ParseResult:
    # Personal conversations never carry the carrier's [Web발신] tag.
    if not has_sms_tag(raw.body):
        return ParseResult(Status.DROPPED, reason="personal SMS")
    if is_otp(text):
        return ParseResult(Status.DROPPED, reason="authentication SMS")

    sender = clean(raw.clean_title)
    if sched := parse_schedule(raw, sender):
        return ParseResult(Status.SCHEDULE, parser=sched.parser, schedule=sched)
    if tx := parse_card_sms(raw):
        return ParseResult(Status.TRANSACTION, parser=tx.parser, transaction=tx)
    if tx := parse_bank_sms(raw):
        return ParseResult(Status.TRANSACTION, parser=tx.parser, transaction=tx)
    if looks_like_money_movement(text) and not any(k in text for k in ("발송", "배송", "주문", "세금안내")):
        return ParseResult(Status.UNPARSED, reason="SMS with money but no rule matched")
    # Marketing / delivery / tax notices: not ours, don't keep the text.
    return ParseResult(Status.DROPPED, reason="non-financial SMS")
