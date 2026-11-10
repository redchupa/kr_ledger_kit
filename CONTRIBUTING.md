# Contributing

## 새 카드사 / 은행 형식 추가하기

1. 알림 원문을 **익명화**합니다. 실제 이름·계좌번호·카드번호·전화번호는 절대 올리지 마세요.

   ```bash
   python tools/anonymize.py --owner 홍길동 < my_notification.json
   ```

2. `tests/fixtures/notifications.json` 에 익명화한 알림과 기대 결과(`expect`)를 추가합니다.
3. 형식에 맞는 파서를 고칩니다.
   - 카드 승인 문자: `engine/sms_card.py` (대부분 줄 역할 판별로 자동 처리됨. 카드사 키워드만 `CARD_ISSUERS` 에 추가)
   - 은행 문자: `engine/sms_bank.py`
   - 앱 푸시: `engine/apps.py` 에 함수 추가 후 `APP_PARSERS` 에 패키지명 등록, `engine/filters.py` 의 `FINANCIAL_PACKAGES` 에도 등록
   - 결제 예정 안내: `engine/schedule.py`
4. `pytest` 와 `ruff check .` 가 통과하는지 확인 후 PR을 보내 주세요.

## 원칙

- `engine/` 패키지는 Home Assistant를 import 하지 않습니다 (HA 없이 테스트 가능해야 함).
- 개인 문자는 어떤 경우에도 저장하지 않습니다. 필터를 느슨하게 만드는 변경은 테스트로 근거를 보여 주세요.
- 금액·날짜를 틀리는 것보다 "확인 필요"로 넘기는 편이 낫습니다.
