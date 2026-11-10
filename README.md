# KR Ledger (가계부) for Home Assistant

카드·은행·페이 **알림을 자동으로 읽어 날짜별 가계부**를 만들어 주는 Home Assistant 통합입니다.
안드로이드 컴패니언 앱의 `Last notification` 센서만 있으면 되고, 모든 데이터는 **내 HA 안에만** 저장됩니다.

> English summary at the bottom.

## 무엇을 해 주나요

- 카드 승인 문자, 카드사 앱, 은행 앱, 삼성페이 알림 → 거래 내역으로 자동 기록
- **같은 결제가 문자·카드앱·삼성페이로 여러 번 와도 1건으로 합침**
- 승인 취소는 지출에서 차감, 해외 결제(USD 등)는 따로 집계
- **본인 계좌 간 이체**와 카드대금 납부는 지출에서 제외 (이중 계산 방지)
- 카드 결제 예정, 대출 납입 예정 같은 안내는 "다가오는 결제"로 표시
- 사이드바 **가계부 패널**: 월간 달력 · 일별 내역 · 분류별 지출 · 수정/삭제 · 직접 추가
- 분류를 한 번 고치면 **같은 사용처는 다음부터 자동 분류**
- 개인/사업 계좌 구분, 특정 카드·계좌를 합계에서 제외
- 센서: 오늘 지출, 이번 달 지출/수입, 최근 거래, 확인 필요 알림 수
- 이벤트 `kr_ledger_transaction` 으로 자동화 가능 (예: 10만 원 이상 결제 시 TTS)

## 지원하는 알림 (v0.1)

| 종류 | 발신처 |
|---|---|
| 카드 승인 문자 | 롯데(개인/법인), 현대, KB국민, 하나, 삼성 형식 + 같은 형식의 카드사 |
| 카카오톡 알림톡 (실험적) | 카드·은행 채널에서 온 승인·입출금 알림 (문자와 같은 형식일 때) |
| 카드 앱 | 하나카드(하나Pay) |
| 은행 앱 | 카카오뱅크, 토스/토스뱅크, 신한 SOL |
| 은행 문자 | 신한은행 등 `[○○은행]` 형식 |
| 페이 | 삼성페이 |
| 예정 안내 | 롯데·현대·KB·하나 결제예정, 카카오뱅크 대출 납입, 토스 출금 예정 |

인식하지 못한 금융 알림은 패널의 **확인 필요** 탭에 모입니다. 자주 쓰는 카드사 형식이 빠져 있으면
[새 알림 형식 제보](../../issues/new?template=new_format.yml)로 알려 주세요.

## 설치

### 1. 컴패니언 앱 준비 (안드로이드)

1. HA 컴패니언 앱 → 설정 → 컴패니언 앱 → **센서 관리** → **Last notification** 켜기
2. 같은 화면의 **허용 목록(Allow list)** 에 카드·은행·페이 앱과 **문자 앱**(알림톡을 쓰면 **카카오톡**도)을 추가
   - 문자·카카오톡은 앱 단위로만 허용할 수 있어 개인 대화도 HA로 넘어옵니다.
     KR Ledger는 개인 문자(`[Web발신]` 표시가 없고 회사 대표번호가 아닌 문자), 개인 카톡, 인증번호를
     **저장하지 않고 즉시 버립니다.**
3. **Active notification count** 센서도 켜기 (강력 권장)
   - 결제 한 번에 문자·카드앱·삼성페이 알림이 거의 동시에 오면, `Last notification` 센서에는
     내용 없는 "묶음 알림"만 남고 실제 알림이 빠지는 경우가 있습니다. 실제 사용 데이터에서 삼성페이 알림
     7건 중 6건이 이렇게 내용 없이 들어왔고, 결제 1건은 통째로 누락됐습니다.
   - Active notification count 센서는 알림창에 떠 있는 알림 전체를 내용과 함께 보내 주므로
     이 누락을 메워 줍니다. 두 센서를 함께 선택하면 같은 알림은 한 번만 기록됩니다.

> iOS 컴패니언 앱에는 알림 센서가 없어 지원하지 않습니다.

### 2. HACS로 설치

1. HACS → 오른쪽 위 ⋮ → **사용자 지정 저장소** → `https://github.com/redchupa/kr_ledger_kit` (유형: Integration)
2. **KR Ledger** 설치 → HA 재시작
3. 설정 → 기기 및 서비스 → 통합 추가 → **KR Ledger**
   - 알림 센서 선택: `sensor.내폰_last_notification` 과 `sensor.내폰_active_notification_count` (여러 대 가능)
   - 본인 이름 입력 (본인 계좌 간 이체 판별용, `홍*동` 같은 가린 이름도 자동 인식)
   - 과거 기록 가져오기: HA 기록에 남아 있는 최근 알림(기본 10일)을 바로 가계부로 가져옵니다

사이드바에 **가계부** 메뉴가 생깁니다.

## 개인정보

- 데이터는 `/config/kr_ledger/ledger.db` (SQLite)에만 저장되며 외부로 전송하지 않습니다.
- 개인 문자, 인증번호, 증권 뉴스·광고 알림은 저장하지 않습니다.
- 알림 원문은 기본 90일 뒤 삭제됩니다 (가계부 내역은 유지). 옵션에서 조절할 수 있습니다.

## 자동화 예시

```yaml
triggers:
  - trigger: event
    event_type: kr_ledger_transaction
    event_data:
      kind: expense
conditions:
  - "{{ trigger.event.data.amount >= 100000 }}"
actions:
  - action: notify.notify
    data:
      message: "{{ trigger.event.data.merchant }}에서 {{ trigger.event.data.amount }}원 결제"
```

## 서비스

| 서비스 | 설명 |
|---|---|
| `kr_ledger.import_history` | HA 기록에서 과거 알림 가져오기 (중복 없음) |
| `kr_ledger.add_transaction` | 현금 등 직접 추가 |
| `kr_ledger.delete_transaction` | 내역 삭제(숨김) |
| `kr_ledger.reprocess` | 업데이트 후 미인식 알림 다시 분석 |

## 개발

```bash
pip install pytest ruff
pytest
ruff check .
```

알림 해석은 Home Assistant와 무관한 순수 파이썬(`custom_components/kr_ledger/engine/`)이라 HA 없이 테스트할 수 있습니다.
새 카드사 지원은 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.

---

## English

KR Ledger turns Korean card / bank / pay notifications captured by the Android Home Assistant companion app
(`Last notification` sensor) into a daily household ledger with a sidebar panel. It merges duplicate reports of
one payment (SMS + card app + Samsung Pay), handles cancellations, foreign currency, transfers between your own
accounts and upcoming bills, and learns categories per merchant. Personal SMS are dropped before anything is
stored, and all data stays in your Home Assistant.

License: MIT
