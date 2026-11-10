"""Decide which notifications are allowed into the ledger at all.

The companion app can only allow-list whole packages, so the SMS app sends
*every* text message - including personal conversations. Those must be
dropped here, before anything is stored.
"""

from __future__ import annotations

import re

from .normalize import SMS_TAGS, clean

MESSAGING_PACKAGES: frozenset[str] = frozenset(
    {
        "com.samsung.android.messaging",
        "com.google.android.apps.messaging",
        "com.android.mms",
        "com.android.messaging",
        "com.lge.message",
        "com.sec.mms",
    }
)

# Financial apps whose notifications are worth looking at. Notifications from
# any other package are dropped unless the user adds the package in options.
FINANCIAL_PACKAGES: dict[str, str] = {
    # banks
    "com.kakaobank.channel": "카카오뱅크",
    "viva.republica.toss": "토스",
    "com.shinhan.sbanking": "신한은행",
    "com.kbstar.kbbank": "KB국민은행",
    "com.kbstar.liivbank": "KB스타뱅킹",
    "com.wooribank.smart.npib": "우리은행",
    "com.wooribank.smart.wwms": "우리WON뱅킹",
    "com.kebhana.hanapush": "하나은행",
    "nh.smart.banking": "NH농협은행",
    "com.ibk.android.ionebank": "IBK기업은행",
    "com.kbankwith.smartbank": "케이뱅크",
    "kr.co.citibank.citimobile": "씨티은행",
    "com.epost.psf.sdsi": "우체국",
    "kr.co.kfcc.mobilebank": "새마을금고",
    "com.cu.sbank": "신협",
    # cards
    "com.hanaskcard.paycla": "하나카드",
    "com.hanaskcard.rocomo.potal": "하나카드",
    "com.lcacApp": "롯데카드",
    "com.lottemembers.android": "롯데카드",
    "com.hyundaicard.appcard": "현대카드",
    "com.kbcard.cxh.appcard": "KB국민카드",
    "com.shcard.smartpay": "신한카드",
    "kr.co.samsungcard.mpocket": "삼성카드",
    "com.wooricard.smartapp": "우리카드",
    "com.bccard.bcpaybooc": "BC카드",
    "nh.smart.nhallonepay": "NH농협카드",
    # pay
    "com.samsung.android.spay": "삼성페이",
    "com.nhnent.payapp": "페이코",
    "com.naverfin.payapp": "네이버페이",
    "com.kakaopay.app": "카카오페이",
}

# KakaoTalk carries both personal chats and 알림톡 from card/bank channels.
KAKAO_PACKAGES: frozenset[str] = frozenset({"com.kakao.talk"})

# A chat / SMS sender that is a company, not a person: 1588-0000 style
# representative numbers, or a channel / contact name mentioning a bank or card.
_REP_NUMBER_RE = re.compile(r"^1[5-9]\d{2}-?\d{4}$")
_FIN_SENDER_RE = re.compile(r"카드|은행|뱅크|페이|증권|캐피탈|저축|금고|신협|Pay|PAY|Bank|BANK")

_OTP_RE = re.compile(r"인증번호|본인확인|OTP|인증 ?요청|보안코드|승인번호\s*\[?\d{4,}")
_MONEY_RE = re.compile(r"[\d,]+\s*원|₩\s*[\d,]+|USD\s*[\d.,]+")
_MOVE_RE = re.compile(r"승인|취소|입금|출금|결제|이체|송금|납부|환불")


def is_messaging(package: str) -> bool:
    return package in MESSAGING_PACKAGES


def is_kakao(package: str) -> bool:
    return package in KAKAO_PACKAGES


def is_chat(package: str) -> bool:
    """Apps whose notifications carry a per-message ``android.messages`` list."""
    return package in MESSAGING_PACKAGES or package in KAKAO_PACKAGES


def is_financial_sender(sender: str) -> bool:
    sender = clean(sender)
    return bool(_REP_NUMBER_RE.match(sender) or _FIN_SENDER_RE.search(sender))


def is_financial_package(package: str, extra: frozenset[str] | set[str] = frozenset()) -> bool:
    return package in FINANCIAL_PACKAGES or package in extra


def has_sms_tag(body: str) -> bool:
    body = clean(body)
    return any(tag in body for tag in SMS_TAGS)


def is_otp(text: str) -> bool:
    return bool(_OTP_RE.search(text))


def looks_like_money_movement(text: str) -> bool:
    return bool(_MONEY_RE.search(text) and _MOVE_RE.search(text))
