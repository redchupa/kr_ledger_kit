"""Anonymise a notification before sharing it in an issue or test fixture.

Usage:
    python tools/anonymize.py --owner 홍길동 [--owner 다른이름] < input.json > output.json

Input: a JSON object (or list) with title / body / text fields, e.g. a row copied
from the panel's review tab or from Developer tools > States.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys

PHONE_RE = re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b")
ACCOUNT_RE = re.compile(r"\b\d{2,6}-[\d*]{2,6}-[\d*]{2,8}\b")
CARD_DIGITS_RE = re.compile(r"(?<=[가-힣A-Za-z])(\d{4})(?!\d)")
PAREN_DIGITS_RE = re.compile(r"\((\d{4})\)")
LONG_NUMBER_RE = re.compile(r"\b\d{9,}\b")
OTP_RE = re.compile(r"(인증번호\s*\[?)(\d{4,8})")
BALANCE_RE = re.compile(r"(잔액|누적(?:이용금액)?)\s*([\d,]+)")


def _digits(match: re.Match, keep: str = "") -> str:
    return re.sub(r"\d", lambda _: str(random.randint(0, 9)), match.group(0))


def _mask_name(name: str) -> list[str]:
    forms = {name}
    if len(name) >= 2:
        forms.add(name[0] + "*" + name[-1] if len(name) == 3 else name[0] + "*" * (len(name) - 1))
        forms.add(name[0] + "*" + name[2:] if len(name) > 2 else name)
    return sorted(forms, key=len, reverse=True)


def anonymise(text: str, owners: list[str]) -> str:
    for owner in owners:
        for form in _mask_name(owner):
            masked = "홍*동" if "*" in form else "홍길동"
            text = text.replace(form, masked)
    text = PHONE_RE.sub("010-0000-0000", text)
    text = ACCOUNT_RE.sub(_digits, text)
    text = OTP_RE.sub(lambda m: m.group(1) + "000000", text)
    text = LONG_NUMBER_RE.sub(_digits, text)
    text = PAREN_DIGITS_RE.sub(lambda m: f"({random.randint(1000, 9999)})", text)
    text = CARD_DIGITS_RE.sub(lambda m: f"{random.randint(1000, 9999)}", text)
    text = BALANCE_RE.sub(lambda m: f"{m.group(1)}{random.randint(1, 999):,}000", text)
    return text


def _walk(value, owners):
    if isinstance(value, str):
        return anonymise(value, owners)
    if isinstance(value, list):
        return [_walk(v, owners) for v in value]
    if isinstance(value, dict):
        return {k: _walk(v, owners) for k, v in value.items()}
    return value


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--owner", action="append", default=[], help="your real name (repeatable)")
    args = ap.parse_args()
    data = json.load(sys.stdin)
    json.dump(_walk(data, args.owner), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
